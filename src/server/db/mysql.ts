/**
 * Mock MySQL layer — returns mock data instead of real DB queries.
 */

const MOCK_DATA: Record<string, Record<string, unknown>[]> = {
  DailyPerformanceSummary: [
    { performance_date: '2026-03-14', idBranch: 1, branch_name: 'Riyadh Main', daily_visits: 245, daily_revenue: 18500.50, total_orders: 89, unique_customers: 156, new_customers: 12, avg_order_value: 207.87, idMerchant: 1032 },
    { performance_date: '2026-03-13', idBranch: 1, branch_name: 'Riyadh Main', daily_visits: 232, daily_revenue: 17200.00, total_orders: 78, unique_customers: 142, new_customers: 8, avg_order_value: 220.51, idMerchant: 1032 },
    { performance_date: '2026-03-14', idBranch: 2, branch_name: 'Jeddah', daily_visits: 189, daily_revenue: 14300.75, total_orders: 65, unique_customers: 120, new_customers: 15, avg_order_value: 220.01, idMerchant: 1032 },
    { performance_date: '2026-03-13', idBranch: 2, branch_name: 'Jeddah', daily_visits: 178, daily_revenue: 13100.00, total_orders: 61, unique_customers: 110, new_customers: 10, avg_order_value: 214.75, idMerchant: 1032 },
  ],
  MerchantSummary: [
    { idMerchant: 1032, total_customers: 8542, total_revenue: 1250000.00, total_visits: 45230, total_branches: 5, total_orders: 12450, avg_order_value: 100.40 },
  ],
  CustomerSummary: [
    { idCustomer: 1, customer_name: 'Ahmed Al-Rashid', segment: 'superFan', total_visits: 85, total_spend: 12500.00, registration_date: '2024-06-15', last_visit_date: '2026-03-12', idMerchant: 1032 },
    { idCustomer: 2, customer_name: 'Sara Mohammed', segment: 'loyal', total_visits: 42, total_spend: 6800.00, registration_date: '2024-09-20', last_visit_date: '2026-03-10', idMerchant: 1032 },
    { idCustomer: 3, customer_name: 'Khalid Omar', segment: 'new', total_visits: 3, total_spend: 450.00, registration_date: '2026-02-28', last_visit_date: '2026-03-08', idMerchant: 1032 },
  ],
  LoyaltyProgramSummary: [
    { segment: 'superFan', total_members: 342, loyalty_score: 92.5, points_earned: 125000, points_redeemed: 89000, idMerchant: 1032 },
    { segment: 'loyal', total_members: 1250, loyalty_score: 75.2, points_earned: 340000, points_redeemed: 210000, idMerchant: 1032 },
    { segment: 'regular', total_members: 2890, loyalty_score: 45.8, points_earned: 180000, points_redeemed: 95000, idMerchant: 1032 },
    { segment: 'new', total_members: 1560, loyalty_score: 20.1, points_earned: 45000, points_redeemed: 12000, idMerchant: 1032 },
    { segment: 'lost', total_members: 2500, loyalty_score: 5.3, points_earned: 89000, points_redeemed: 78000, idMerchant: 1032 },
  ],
  GeographicPerformanceSummary: [
    { idBranch: 1, branch_name: 'Riyadh Main', total_visits: 15200, total_revenue: 580000, total_orders: 4200, avg_order_value: 138.10, idMerchant: 1032 },
    { idBranch: 2, branch_name: 'Jeddah', total_visits: 12100, total_revenue: 465000, total_orders: 3400, avg_order_value: 136.76, idMerchant: 1032 },
    { idBranch: 3, branch_name: 'Dammam', total_visits: 8400, total_revenue: 312000, total_orders: 2300, avg_order_value: 135.65, idMerchant: 1032 },
  ],
  CampaignSummary: [
    { campaign_id: 1, campaign_name: 'Ramadan Special', status: 'completed', total_sent: 5000, total_redeemed: 1200, redemption_rate: 24.0, revenue_generated: 85000, idMerchant: 1032 },
    { campaign_id: 2, campaign_name: 'New Year Promo', status: 'active', total_sent: 3500, total_redeemed: 800, redemption_rate: 22.9, revenue_generated: 52000, idMerchant: 1032 },
  ],
  PickupOrderSummary: [
    { status: 'done', total_orders: 8500, percentage: 68.3, idMerchant: 1032 },
    { status: 'rejected', total_orders: 1200, percentage: 9.6, idMerchant: 1032 },
    { status: 'returned', total_orders: 450, percentage: 3.6, idMerchant: 1032 },
    { status: 'timeout', total_orders: 2300, percentage: 18.5, idMerchant: 1032 },
  ],
  MonthlyPerformanceSummary: [
    { year: 2026, month: 2, idBranch: 1, branch_name: 'Riyadh Main', monthly_visits: 6800, monthly_revenue: 510000, monthly_orders: 2100, idMerchant: 1032 },
    { year: 2026, month: 1, idBranch: 1, branch_name: 'Riyadh Main', monthly_visits: 7200, monthly_revenue: 545000, monthly_orders: 2300, idMerchant: 1032 },
  ],
  PaymentAnalyticsSummary: [
    { payment_method: 'card', channel: 'in_store', total_transactions: 6500, total_revenue: 780000, percentage: 62.4, idMerchant: 1032 },
    { payment_method: 'cash', channel: 'in_store', total_transactions: 3200, total_revenue: 320000, percentage: 25.6, idMerchant: 1032 },
    { payment_method: 'digital', channel: 'online', total_transactions: 1500, total_revenue: 150000, percentage: 12.0, idMerchant: 1032 },
  ],
  POSComparisonSummary: [
    { product_name: 'Latte', total_sold: 4500, total_revenue: 67500, avg_price: 15.0, idMerchant: 1032 },
    { product_name: 'Cappuccino', total_sold: 3200, total_revenue: 51200, avg_price: 16.0, idMerchant: 1032 },
    { product_name: 'Americano', total_sold: 2800, total_revenue: 36400, avg_price: 13.0, idMerchant: 1032 },
  ],
};

export async function executeQuery(
  query: string,
  tableName?: string
): Promise<{
  success: boolean;
  data?: Record<string, unknown>[];
  rowCount?: number;
  columns?: string[];
  error?: string;
  timeout?: boolean;
}> {
  console.log(`[Mock MySQL] Query: ${query.slice(0, 200)}`);

  // Extract table name from query if not provided
  const resolvedTable = tableName || extractTableName(query);
  if (!resolvedTable) {
    return { success: false, error: 'Could not determine table from query' };
  }

  const data = MOCK_DATA[resolvedTable];
  if (!data) {
    return { success: true, data: [], rowCount: 0, columns: [] };
  }

  // Return mock data
  const columns = data.length > 0 ? Object.keys(data[0]) : [];
  console.log(`[Mock MySQL] Returning ${data.length} mock rows from ${resolvedTable}`);
  return {
    success: true,
    data: [...data],
    rowCount: data.length,
    columns,
  };
}

export async function checkDataExists(
  tableName: string,
  _merchantId: string
): Promise<boolean> {
  return tableName in MOCK_DATA;
}

export async function getMysqlSchemas(): Promise<Record<string, string>> {
  // Return mock schemas
  const schemas: Record<string, string> = {};
  for (const tableName of Object.keys(MOCK_DATA)) {
    schemas[tableName] = `CREATE TABLE ${tableName} (mock schema)`;
  }
  return schemas;
}

export async function pingMysql(): Promise<boolean> {
  return true; // Mock always healthy
}

function extractTableName(query: string): string | null {
  const match = query.match(/FROM\s+`?(\w+)`?/i);
  return match ? match[1] : null;
}
