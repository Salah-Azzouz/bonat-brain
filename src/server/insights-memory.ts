/**
 * Mock insights memory — no-op storage for insights that have been shown.
 *
 * In production, this would track which insights have been shown to
 * avoid repeating them and to measure engagement.
 */

export interface InsightRecord {
  insightId: string;
  merchantId: string;
  shownAt: Date;
  dismissed: boolean;
  interacted: boolean;
}

export class InsightsMemory {
  constructor() {
    console.log('[InsightsMemory] Initialized (mode=mock)');
  }

  async recordShown(
    _insightId: string,
    _merchantId: string
  ): Promise<void> {
    // Mock: no-op
  }

  async recordDismissed(
    _insightId: string,
    _merchantId: string
  ): Promise<void> {
    // Mock: no-op
  }

  async recordInteraction(
    _insightId: string,
    _merchantId: string
  ): Promise<void> {
    // Mock: no-op
  }

  async wasRecentlyShown(
    _insightId: string,
    _merchantId: string,
    _withinHours: number = 24
  ): Promise<boolean> {
    // Mock: never recently shown
    return false;
  }

  async getShownInsights(
    _merchantId: string,
    _limit: number = 50
  ): Promise<InsightRecord[]> {
    // Mock: empty
    return [];
  }

  async clearHistory(_merchantId: string): Promise<void> {
    // Mock: no-op
  }
}

// Singleton
let _memory: InsightsMemory | null = null;

export function getInsightsMemory(): InsightsMemory {
  if (!_memory) {
    _memory = new InsightsMemory();
  }
  return _memory;
}
