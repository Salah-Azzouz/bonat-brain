/**
 * Mock example store — always returns empty array.
 *
 * In production, this would:
 * 1. Embed the user query
 * 2. Search Qdrant for similar past queries
 * 3. Return the top-k matched examples with their SQL and results
 */

export interface StoredExample {
  userPrompt: string;
  table: string;
  query: string;
  similarity: number;
}

export class ExampleStore {
  constructor() {
    console.log('[ExampleStore] Initialized (mode=mock)');
  }

  async findSimilar(
    _userPrompt: string,
    _topK: number = 3,
    _threshold: number = 0.8
  ): Promise<StoredExample[]> {
    // Mock: always return empty
    return [];
  }

  async addExample(
    _userPrompt: string,
    _table: string,
    _query: string
  ): Promise<void> {
    // Mock: no-op
  }

  async removeExample(_userPrompt: string): Promise<void> {
    // Mock: no-op
  }

  async count(): Promise<number> {
    return 0;
  }
}

// Singleton
let _store: ExampleStore | null = null;

export function getExampleStore(): ExampleStore {
  if (!_store) {
    _store = new ExampleStore();
  }
  return _store;
}
