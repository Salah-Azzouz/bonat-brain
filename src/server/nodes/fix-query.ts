/**
 * LLM-based SQL fix node — attempts to repair a failed SQL query.
 */

import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';
import type { PipelineState } from './types';
import { LLM_MODEL_NAME } from '../config';

export interface FixQueryResult {
  generatedQuery: string;
  querySource: 'fallback';
  errorMessage: string | null;
}

export async function fixQuery(state: PipelineState): Promise<FixQueryResult> {
  const { generatedQuery, errorMessage, selectedTable, tableSchema, merchantId, userPrompt } =
    state;

  console.log(`[fixQuery] Attempting to fix query for table: ${selectedTable}`);
  console.log(`[fixQuery] Error was: ${errorMessage}`);

  const systemPrompt = `You are a MySQL query repair expert. A query failed with an error. Fix it.

Table: ${selectedTable}
Schema: ${tableSchema}
Merchant ID: ${merchantId}

Original query:
${generatedQuery}

Error:
${errorMessage}

Rules:
- Always include WHERE idMerchant = ${merchantId}
- Only use SELECT (no INSERT/UPDATE/DELETE)
- Use backticks for column and table names
- Add LIMIT 100 if no limit specified
- Return only the corrected SQL query, no explanation`;

  try {
    const { text } = await generateText({
      model: openai(LLM_MODEL_NAME),
      messages: [
        { role: 'system', content: systemPrompt },
        {
          role: 'user',
          content: `Fix this query for the user's question: "${userPrompt}"`,
        },
      ],
    });

    const fixedQuery = extractSql(text);
    console.log(`[fixQuery] Fixed query: ${fixedQuery.slice(0, 200)}`);

    return {
      generatedQuery: fixedQuery,
      querySource: 'fallback',
      errorMessage: null,
    };
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error(`[fixQuery] LLM fix failed: ${errMsg}`);
    return {
      generatedQuery: generatedQuery,
      querySource: 'fallback',
      errorMessage: `Fix attempt failed: ${errMsg}`,
    };
  }
}

function extractSql(text: string): string {
  const codeBlockMatch = text.match(/```(?:sql)?\s*\n?([\s\S]*?)\n?```/);
  if (codeBlockMatch) return codeBlockMatch[1].trim();

  const sqlMatch = text.match(/SELECT[\s\S]*/i);
  if (sqlMatch) return sqlMatch[0].trim();

  return text.trim();
}
