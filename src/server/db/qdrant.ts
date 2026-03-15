/**
 * Mock Qdrant layer — returns mock embeddings and search results.
 */

export function getQdrantClient() {
  return {
    search: async () => [],
    upsert: async () => {},
    getCollections: async () => ({ collections: [] }),
    scroll: async () => [[], null],
    getCollection: async () => ({ points_count: 0 }),
  };
}

export async function embedTexts(texts: string[]): Promise<number[][]> {
  // Return mock embeddings (random unit vectors)
  return texts.map(() => {
    const vec = Array.from({ length: 3072 }, () => Math.random() - 0.5);
    const norm = Math.sqrt(vec.reduce((sum, v) => sum + v * v, 0));
    return vec.map(v => v / norm);
  });
}

export async function embedText(text: string): Promise<number[]> {
  const results = await embedTexts([text]);
  return results[0];
}

export const EMBEDDING_DIMENSION = 3072;
