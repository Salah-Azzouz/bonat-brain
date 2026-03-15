/**
 * Mock semantic cache — always returns null for get, no-op for put.
 *
 * In production, this would:
 * 1. Embed the query
 * 2. Search for semantically similar cached queries in Qdrant
 * 3. Return cached result if similarity > threshold
 */

export interface CachedResult {
  query: string;
  result: unknown;
  timestamp: number;
  similarity: number;
}

export class SemanticCache {
  private enabled: boolean;

  constructor(enabled: boolean = false) {
    this.enabled = enabled;
    console.log(`[SemanticCache] Initialized (enabled=${enabled}, mode=mock)`);
  }

  async get(
    _userPrompt: string,
    _merchantId: string,
    _threshold: number = 0.95
  ): Promise<CachedResult | null> {
    // Mock: always cache miss
    return null;
  }

  async put(
    _userPrompt: string,
    _merchantId: string,
    _tableName: string,
    _query: string,
    _result: unknown
  ): Promise<void> {
    // Mock: no-op
  }

  async invalidate(_merchantId: string): Promise<void> {
    // Mock: no-op
  }

  async clear(): Promise<void> {
    // Mock: no-op
  }

  isEnabled(): boolean {
    return this.enabled;
  }
}

// Singleton
let _cache: SemanticCache | null = null;

export function getSemanticCache(): SemanticCache {
  if (!_cache) {
    _cache = new SemanticCache(false);
  }
  return _cache;
}
