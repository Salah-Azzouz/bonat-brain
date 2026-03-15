/**
 * Executes SQL against the mock database.
 */

import type { PipelineState } from './types';
import { executeQuery as dbExecuteQuery } from '../db/mysql';

export interface ExecuteQueryResult {
  executionResult: PipelineState['executionResult'];
  errorMessage: string | null;
}

export async function executeQueryNode(state: PipelineState): Promise<ExecuteQueryResult> {
  const { generatedQuery, selectedTable } = state;

  if (!generatedQuery) {
    return {
      executionResult: {
        success: false,
        error: 'No query to execute',
      },
      errorMessage: 'No query was generated',
    };
  }

  console.log(`[executeQuery] Executing query on table: ${selectedTable}`);

  try {
    const result = await dbExecuteQuery(generatedQuery, selectedTable);

    if (!result.success) {
      console.warn(`[executeQuery] Query failed: ${result.error}`);
      return {
        executionResult: result,
        errorMessage: result.error || 'Query execution failed',
      };
    }

    console.log(`[executeQuery] Success: ${result.rowCount} rows returned`);
    return {
      executionResult: result,
      errorMessage: null,
    };
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    console.error(`[executeQuery] Exception: ${errorMsg}`);
    return {
      executionResult: {
        success: false,
        error: errorMsg,
      },
      errorMessage: errorMsg,
    };
  }
}
