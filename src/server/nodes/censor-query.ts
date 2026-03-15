/**
 * Security check: ensures idMerchant is present in the WHERE clause.
 * Prevents cross-tenant data access.
 */

import type { PipelineState } from './types';

export interface CensorQueryResult {
  generatedQuery: string;
  errorMessage: string | null;
}

export function censorQuery(state: PipelineState): CensorQueryResult {
  const { generatedQuery, merchantId } = state;

  if (!generatedQuery) {
    return {
      generatedQuery: '',
      errorMessage: 'No query to censor',
    };
  }

  const queryUpper = generatedQuery.toUpperCase();

  // Check for forbidden statements
  const forbidden = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'TRUNCATE', 'CREATE'];
  for (const keyword of forbidden) {
    if (queryUpper.includes(keyword)) {
      console.warn(`[censorQuery] Blocked forbidden keyword: ${keyword}`);
      return {
        generatedQuery: '',
        errorMessage: `Query contains forbidden operation: ${keyword}`,
      };
    }
  }

  // Check that idMerchant filter is present
  const merchantPatterns = [
    new RegExp(`idMerchant\\s*=\\s*${merchantId}`, 'i'),
    new RegExp(`\`idMerchant\`\\s*=\\s*${merchantId}`, 'i'),
    new RegExp(`idmerchant\\s*=\\s*'${merchantId}'`, 'i'),
    new RegExp(`\`idMerchant\`\\s*=\\s*'${merchantId}'`, 'i'),
  ];

  const hasMerchantFilter = merchantPatterns.some((p) => p.test(generatedQuery));

  if (!hasMerchantFilter) {
    console.warn('[censorQuery] idMerchant filter missing — injecting');

    // Try to inject idMerchant into WHERE clause
    const whereMatch = generatedQuery.match(/\bWHERE\b/i);
    let fixedQuery: string;

    if (whereMatch) {
      fixedQuery = generatedQuery.replace(
        /\bWHERE\b/i,
        `WHERE \`idMerchant\` = ${merchantId} AND`
      );
    } else {
      // No WHERE clause at all — add one before GROUP BY, ORDER BY, LIMIT, or end
      const insertPoint = generatedQuery.match(
        /\b(GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING)\b/i
      );
      if (insertPoint && insertPoint.index !== undefined) {
        fixedQuery =
          generatedQuery.slice(0, insertPoint.index) +
          `WHERE \`idMerchant\` = ${merchantId} ` +
          generatedQuery.slice(insertPoint.index);
      } else {
        fixedQuery = generatedQuery + ` WHERE \`idMerchant\` = ${merchantId}`;
      }
    }

    console.log('[censorQuery] Injected idMerchant filter');
    return {
      generatedQuery: fixedQuery,
      errorMessage: null,
    };
  }

  return {
    generatedQuery,
    errorMessage: null,
  };
}
