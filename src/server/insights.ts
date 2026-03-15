/**
 * Mock insights — returns false for shouldShow checks.
 *
 * In production, this would analyze query results to surface
 * noteworthy patterns, anomalies, and trends.
 */

export interface Insight {
  type: 'anomaly' | 'trend' | 'milestone' | 'comparison';
  title: string;
  description: string;
  severity: 'info' | 'warning' | 'positive' | 'negative';
}

export function shouldShowInsights(
  _tableName: string,
  _data: Record<string, unknown>[],
  _merchantId: string
): boolean {
  // Mock: never show insights
  return false;
}

export function generateInsights(
  _tableName: string,
  _data: Record<string, unknown>[],
  _merchantId: string
): Insight[] {
  // Mock: return empty array
  return [];
}

export function getInsightForMetric(
  _metricName: string,
  _currentValue: number,
  _previousValue?: number
): Insight | null {
  // Mock: no insights
  return null;
}
