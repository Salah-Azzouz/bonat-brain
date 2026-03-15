/**
 * Main data pipeline orchestrator.
 *
 * Runs: security check -> selectTable -> validateRequest -> createQuery ->
 *       censorQuery -> executeQuery with retry (self-correction).
 *
 * Includes:
 * - Self-correction with fallback table on failure
 * - Scope warnings for lifetime tables
 * - NULL/zero result context
 * - Retry with LLM fix
 */

import type { PipelineState } from '../nodes/types';
import { selectTable } from '../nodes/select-table';
import { validateRequest } from '../nodes/validate-request';
import { createQuery } from '../nodes/create-query';
import { censorQuery } from '../nodes/censor-query';
import { executeQueryNode } from '../nodes/execute-query';
import { fixQuery } from '../nodes/fix-query';
import { getMerchantNow, formatDate, getDayName } from '../config';

const MAX_RETRIES = 2;

export interface DataPipelineResult {
  success: boolean;
  data?: Record<string, unknown>[];
  rowCount?: number;
  columns?: string[];
  query?: string;
  querySource?: string;
  selectedTable?: string;
  scopeWarning?: string;
  zeroResultContext?: string;
  errorMessage?: string;
}

export async function runDataPipeline(
  userPrompt: string,
  merchantId: string,
  conversationHistory: unknown[] = []
): Promise<DataPipelineResult> {
  // Initialize state
  const now = getMerchantNow();
  const state: PipelineState = {
    userPrompt,
    merchantId,
    conversationHistory,
    history: [],
    confirmedMeaning: '',
    selectedTable: '',
    tableSchema: '',
    validationResult: '',
    dataAvailabilityMessage: '',
    generatedQuery: '',
    executionResult: { success: false },
    errorMessage: null,
    retryCount: 0,
    currentDate: formatDate(now),
    currentDayName: getDayName(now),
  };

  // ── Step 1: Security check (basic prompt validation) ──
  const securityResult = performSecurityCheck(userPrompt);
  if (!securityResult.safe) {
    return {
      success: false,
      errorMessage: securityResult.reason,
    };
  }

  // ── Step 2: Select table ──
  const tableResult = selectTable(state);
  if (!tableResult) {
    return {
      success: false,
      errorMessage: 'Could not determine which data table to query.',
    };
  }

  state.selectedTable = tableResult.selectedTable;
  state.tableSchema = tableResult.tableSchema;
  state.fallbackTable = tableResult.fallbackTable;
  state.fallbackSchema = tableResult.fallbackSchema;

  // ── Step 3: Validate request (check data exists) ──
  const validation = await validateRequest(state);
  state.validationResult = validation.validationResult;
  state.dataAvailabilityMessage = validation.dataAvailabilityMessage;

  if (state.validationResult === 'no_data') {
    return {
      success: false,
      selectedTable: state.selectedTable,
      errorMessage: state.dataAvailabilityMessage,
    };
  }

  // ── Step 4: Create query ──
  const queryResult = await createQuery(state);
  state.generatedQuery = queryResult.generatedQuery;
  state.querySource = queryResult.querySource;
  state.scopeWarning = queryResult.scopeWarning;

  if (queryResult.errorMessage && !state.generatedQuery) {
    return {
      success: false,
      selectedTable: state.selectedTable,
      errorMessage: queryResult.errorMessage,
    };
  }

  // ── Step 5: Censor query (ensure merchant isolation) ──
  const censorResult = censorQuery(state);
  state.generatedQuery = censorResult.generatedQuery;

  if (censorResult.errorMessage && !state.generatedQuery) {
    return {
      success: false,
      selectedTable: state.selectedTable,
      errorMessage: censorResult.errorMessage,
    };
  }

  // ── Step 6: Execute query with retry ──
  let execResult = await executeQueryNode(state);
  state.executionResult = execResult.executionResult;
  state.errorMessage = execResult.errorMessage;

  // Retry loop with self-correction
  while (!state.executionResult.success && state.retryCount < MAX_RETRIES) {
    state.retryCount++;
    console.log(
      `[dataPipeline] Retry ${state.retryCount}/${MAX_RETRIES} for table ${state.selectedTable}`
    );

    // Try LLM fix
    const fixResult = await fixQuery(state);
    state.generatedQuery = fixResult.generatedQuery;
    state.querySource = fixResult.querySource;

    if (fixResult.errorMessage) {
      state.errorMessage = fixResult.errorMessage;
      continue;
    }

    // Re-censor the fixed query
    const reCensor = censorQuery(state);
    state.generatedQuery = reCensor.generatedQuery;

    if (reCensor.errorMessage && !state.generatedQuery) {
      state.errorMessage = reCensor.errorMessage;
      continue;
    }

    // Re-execute
    execResult = await executeQueryNode(state);
    state.executionResult = execResult.executionResult;
    state.errorMessage = execResult.errorMessage;
  }

  // ── Self-correction: try fallback table if primary failed ──
  if (
    !state.executionResult.success &&
    state.fallbackTable &&
    state.fallbackTable !== state.selectedTable
  ) {
    console.log(`[dataPipeline] Trying fallback table: ${state.fallbackTable}`);
    state.selectedTable = state.fallbackTable;
    state.tableSchema = state.fallbackSchema || '';
    state.retryCount = 0;
    state.errorMessage = null;

    const fallbackQuery = await createQuery(state);
    state.generatedQuery = fallbackQuery.generatedQuery;
    state.querySource = fallbackQuery.querySource;
    state.scopeWarning = fallbackQuery.scopeWarning;

    if (state.generatedQuery) {
      const fbCensor = censorQuery(state);
      state.generatedQuery = fbCensor.generatedQuery;

      if (state.generatedQuery) {
        execResult = await executeQueryNode(state);
        state.executionResult = execResult.executionResult;
        state.errorMessage = execResult.errorMessage;
      }
    }
  }

  // ── Final result ──
  if (!state.executionResult.success) {
    return {
      success: false,
      selectedTable: state.selectedTable,
      query: state.generatedQuery,
      querySource: state.querySource,
      errorMessage: state.errorMessage || 'Query execution failed after all retries.',
    };
  }

  // Check for zero/null results
  const zeroResultContext = buildZeroResultContext(state);

  // Check scope warning for lifetime tables
  const scopeWarning = state.scopeWarning || undefined;

  return {
    success: true,
    data: state.executionResult.data,
    rowCount: state.executionResult.rowCount,
    columns: state.executionResult.columns,
    query: state.generatedQuery,
    querySource: state.querySource,
    selectedTable: state.selectedTable,
    scopeWarning,
    zeroResultContext,
  };
}

// ---------------------------------------------------------------------------
// Security check
// ---------------------------------------------------------------------------

interface SecurityCheckResult {
  safe: boolean;
  reason?: string;
}

function performSecurityCheck(prompt: string): SecurityCheckResult {
  const lower = prompt.toLowerCase();

  // Block SQL injection attempts
  const injectionPatterns = [
    /;\s*drop\s+/i,
    /;\s*delete\s+/i,
    /;\s*insert\s+/i,
    /;\s*update\s+/i,
    /union\s+select/i,
    /'\s*or\s+'1'\s*=\s*'1/i,
    /--\s*$/m,
    /\/\*.*\*\//,
  ];

  for (const pattern of injectionPatterns) {
    if (pattern.test(lower)) {
      return { safe: false, reason: 'Request blocked for security reasons.' };
    }
  }

  // Block obviously non-data requests
  if (prompt.trim().length < 2) {
    return { safe: false, reason: 'Please provide a more specific question.' };
  }

  return { safe: true };
}

// ---------------------------------------------------------------------------
// Zero/null result context
// ---------------------------------------------------------------------------

function buildZeroResultContext(state: PipelineState): string | undefined {
  const { executionResult } = state;

  if (!executionResult.success || !executionResult.data) return undefined;

  if (executionResult.rowCount === 0 || executionResult.data.length === 0) {
    return (
      'The query returned no results. This could mean:\n' +
      '- No data exists for the specified time period\n' +
      '- The filters are too restrictive\n' +
      '- The feature is not yet active for this merchant'
    );
  }

  // Check if all numeric values are zero
  const allZero = executionResult.data.every((row) =>
    Object.values(row).every((val) => {
      if (typeof val === 'number') return val === 0;
      return true;
    })
  );

  if (allZero) {
    return (
      'All numeric values in the result are zero. ' +
      'This may indicate the feature has not been actively used during the queried period.'
    );
  }

  // Check for all NULLs
  const allNull = executionResult.data.every((row) =>
    Object.values(row).every((val) => val === null || val === undefined)
  );

  if (allNull) {
    return 'All values in the result are NULL, indicating no data has been recorded yet.';
  }

  return undefined;
}
