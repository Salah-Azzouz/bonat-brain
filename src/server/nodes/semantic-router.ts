/**
 * Mock semantic router — always returns null (no real embeddings).
 *
 * In production, this would:
 * 1. Embed the user query
 * 2. Compare against pre-embedded route examples
 * 3. Return the best matching table if confidence > threshold
 */

export interface SemanticRouterResult {
  table: string;
  confidence: number;
}

export function semanticRoute(_query: string): SemanticRouterResult | null {
  // Mock: no real embeddings available
  return null;
}

export function semanticRouteWithThreshold(
  _query: string,
  _threshold: number = 0.85
): string | null {
  const result = semanticRoute(_query);
  if (result && result.confidence >= _threshold) {
    return result.table;
  }
  return null;
}
