/**
 * Mock suggestions — returns hardcoded follow-up questions per table.
 */

const SUGGESTIONS_BY_TABLE: Record<string, string[]> = {
  DailyPerformanceSummary: [
    'How did today compare to yesterday?',
    'Show me revenue by branch for the last 7 days',
    'Which branch had the most visits today?',
    'What is the average order value this week?',
  ],
  MonthlyPerformanceSummary: [
    'Compare this month to last month',
    'Show monthly revenue trend',
    'Which month had the highest revenue?',
    'How many orders per month this year?',
  ],
  MerchantSummary: [
    'How many total customers do I have?',
    'What is my overall average order value?',
    'Show me a summary of all branches',
    'What are my total lifetime sales?',
  ],
  CustomerSummary: [
    'Who are my top 5 customers?',
    'How many customers are in the SuperFan segment?',
    'Show me new customers this month',
    'Which customers have the highest spend?',
  ],
  LoyaltyProgramSummary: [
    'How many loyalty members do I have?',
    'What is the redemption rate by segment?',
    'Show points earned vs redeemed',
    'Which segment has the highest loyalty score?',
  ],
  GeographicPerformanceSummary: [
    'Which branch has the highest revenue?',
    'Compare performance across all branches',
    'What is the average order value by branch?',
    'Which branch has the most visits?',
  ],
  CampaignSummary: [
    'Which campaign had the highest redemption rate?',
    'Show all active campaigns',
    'What revenue did the Ramadan campaign generate?',
    'How many campaigns are currently running?',
  ],
  PickupOrderSummary: [
    'What percentage of orders are completed?',
    'How many orders were rejected?',
    'Show order status breakdown',
    'What is the timeout rate?',
  ],
  PaymentAnalyticsSummary: [
    'What is the most popular payment method?',
    'Show revenue by payment channel',
    'What percentage of transactions are card payments?',
    'Compare in-store vs online payments',
  ],
  POSComparisonSummary: [
    'What is the best-selling product?',
    'Show top 5 products by revenue',
    'What is the average price per product?',
    'Compare product sales',
  ],
};

const DEFAULT_SUGGESTIONS = [
  'Show me today\'s revenue',
  'How many customers do I have?',
  'Which branch performs best?',
  'Show my loyalty program summary',
];

export function getSuggestions(tableName?: string): string[] {
  if (tableName && SUGGESTIONS_BY_TABLE[tableName]) {
    return SUGGESTIONS_BY_TABLE[tableName];
  }
  return DEFAULT_SUGGESTIONS;
}

export function getFollowUpSuggestions(
  tableName: string,
  _query?: string,
  _result?: unknown
): string[] {
  return getSuggestions(tableName).slice(0, 3);
}
