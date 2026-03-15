/**
 * Creates SQL query using structured output decomposition.
 *
 * 1. Uses OpenAI to generate a QueryIntent JSON via structured output
 * 2. Compiles the intent to SQL using the deterministic compiler
 * 3. Falls back to legacy raw SQL generation on failure
 */

import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';
import type { PipelineState } from './types';
import {
  type QueryIntent,
  QueryIntentSchema,
  getColumnListForPrompt,
  getTimePresetsForPrompt,
  getTimeColumn,
  getTableNotes,
  buildTableQueryIntentSchema,
} from './query-schema';
import { compileToSql } from './compile-query';
import { LLM_MODEL_NAME } from '../config';

export interface CreateQueryResult {
  generatedQuery: string;
  querySource: 'structured' | 'legacy' | 'fallback';
  scopeWarning?: string;
  errorMessage?: string;
}

export async function createQuery(state: PipelineState): Promise<CreateQueryResult> {
  const { userPrompt, selectedTable, merchantId, currentDate, tableSchema } = state;

  // Try structured output first
  try {
    const structuredResult = await createStructuredQuery(
      userPrompt,
      selectedTable,
      merchantId,
      currentDate,
      state.conversationHistory
    );
    if (structuredResult) return structuredResult;
  } catch (err) {
    console.warn('[createQuery] Structured query failed, falling back to legacy:', err);
  }

  // Fall back to legacy raw SQL
  try {
    const legacyResult = await createLegacyQuery(
      userPrompt,
      selectedTable,
      tableSchema,
      merchantId,
      currentDate,
      state.conversationHistory
    );
    return legacyResult;
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    console.error('[createQuery] Legacy query also failed:', errorMsg);
    return {
      generatedQuery: '',
      querySource: 'legacy',
      errorMessage: `Failed to generate query: ${errorMsg}`,
    };
  }
}

// ---------------------------------------------------------------------------
// Structured query generation
// ---------------------------------------------------------------------------

async function createStructuredQuery(
  userPrompt: string,
  tableName: string,
  merchantId: string,
  currentDate: string,
  conversationHistory: unknown[]
): Promise<CreateQueryResult | null> {
  const columnList = getColumnListForPrompt(tableName);
  const timeCol = getTimeColumn(tableName);
  const notes = getTableNotes(tableName);
  const timePresets = getTimePresetsForPrompt();

  const systemPrompt = buildStructuredSystemPrompt(
    tableName,
    columnList,
    timeCol,
    notes,
    timePresets,
    currentDate
  );

  const messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }> = [
    { role: 'system', content: systemPrompt },
  ];

  // Add conversation history context
  for (const turn of conversationHistory.slice(-4)) {
    const t = turn as { role?: string; content?: string };
    if (t.role === 'user' || t.role === 'assistant') {
      messages.push({ role: t.role as 'user' | 'assistant', content: t.content || '' });
    }
  }

  messages.push({ role: 'user', content: userPrompt });

  const { text } = await generateText({
    model: openai(LLM_MODEL_NAME),
    messages,
  });

  // Parse the JSON response
  let intent: QueryIntent;
  try {
    const jsonStr = extractJson(text);
    const tableSchema = buildTableQueryIntentSchema(tableName);
    intent = tableSchema.parse(JSON.parse(jsonStr));
  } catch (parseErr) {
    console.warn('[createQuery] Failed to parse structured output:', parseErr);
    return null;
  }

  // Compile to SQL
  const { query, error, scopeWarning } = compileToSql(intent, tableName, merchantId, currentDate);
  if (!query || error) {
    console.warn('[createQuery] Compile failed:', error);
    return null;
  }

  return {
    generatedQuery: query,
    querySource: 'structured',
    scopeWarning,
  };
}

// ---------------------------------------------------------------------------
// Legacy raw SQL generation
// ---------------------------------------------------------------------------

async function createLegacyQuery(
  userPrompt: string,
  tableName: string,
  tableSchema: string,
  merchantId: string,
  currentDate: string,
  conversationHistory: unknown[]
): Promise<CreateQueryResult> {
  const systemPrompt = `You are a MySQL query generator. Generate a single SELECT query.

Table: ${tableName}
Schema: ${tableSchema}
Merchant ID: ${merchantId}
Current Date: ${currentDate}

Rules:
- Always include WHERE idMerchant = ${merchantId}
- Only use SELECT (no INSERT/UPDATE/DELETE)
- Use backticks for column and table names
- Add LIMIT 100 if no limit specified
- Return only the SQL query, no explanation`;

  const messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }> = [
    { role: 'system', content: systemPrompt },
  ];

  for (const turn of conversationHistory.slice(-4)) {
    const t = turn as { role?: string; content?: string };
    if (t.role === 'user' || t.role === 'assistant') {
      messages.push({ role: t.role as 'user' | 'assistant', content: t.content || '' });
    }
  }

  messages.push({ role: 'user', content: userPrompt });

  const { text } = await generateText({
    model: openai(LLM_MODEL_NAME),
    messages,
  });

  const query = extractSql(text);
  return {
    generatedQuery: query,
    querySource: 'legacy',
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildStructuredSystemPrompt(
  tableName: string,
  columnList: string,
  timeCol: string | null,
  notes: string,
  timePresets: string,
  currentDate: string
): string {
  const timeInfo = timeCol
    ? `This table supports date filtering via column \`${timeCol}\`.\n${timePresets}`
    : 'This table contains LIFETIME totals only. Do NOT specify a time_range.';

  return `You are a data analyst for a loyalty platform. Generate a QueryIntent JSON for table \`${tableName}\`.

Current date: ${currentDate}

Available columns:
${columnList}

${timeInfo}

${notes ? `Notes: ${notes}` : ''}

IMPORTANT:
- Do NOT include idMerchant in filters (auto-added)
- Use only columns listed above
- Return valid JSON matching the QueryIntent schema
- For "top N" questions, use appropriate aggregation + order_by + limit

Respond with ONLY the JSON object, no markdown fences or explanation.`;
}

function extractJson(text: string): string {
  // Try to find JSON in markdown code blocks
  const codeBlockMatch = text.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
  if (codeBlockMatch) return codeBlockMatch[1].trim();

  // Try to find a JSON object directly
  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (jsonMatch) return jsonMatch[0];

  return text.trim();
}

function extractSql(text: string): string {
  // Try to find SQL in markdown code blocks
  const codeBlockMatch = text.match(/```(?:sql)?\s*\n?([\s\S]*?)\n?```/);
  if (codeBlockMatch) return codeBlockMatch[1].trim();

  // Otherwise return the trimmed text, removing any leading/trailing explanation
  const lines = text.trim().split('\n');
  const sqlLines = lines.filter(
    (l) => l.trim().toUpperCase().startsWith('SELECT') || l.trim().startsWith('`') || /^\s/.test(l)
  );
  if (sqlLines.length > 0) {
    return sqlLines.join('\n').trim();
  }

  return text.trim();
}
