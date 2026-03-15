/**
 * Table routing with deterministic regex patterns (ported from Python).
 *
 * Layers:
 * 1. Regex-based deterministic matching (Arabic + English)
 * 2. Semantic router (mock — returns null)
 * 3. Example store (mock — returns null)
 * 4. LLM fallback (mock — returns null)
 */

import type { PipelineState } from './types';
import { getSemanticModel } from '../semantic-model';

// ---------------------------------------------------------------------------
// Mock schemas — used instead of real DB schemas
// ---------------------------------------------------------------------------

const MOCK_SCHEMAS: Record<string, string> = {
  DailyPerformanceSummary:
    'CREATE TABLE DailyPerformanceSummary (idMerchant INT, idBranch INT, branch_name VARCHAR, performance_date DATE, daily_visits INT, daily_revenue DECIMAL, total_orders INT, unique_customers INT, new_customers INT, avg_order_value DECIMAL)',
  MonthlyPerformanceSummary:
    'CREATE TABLE MonthlyPerformanceSummary (idMerchant INT, idBranch INT, branch_name VARCHAR, year INT, month INT, monthly_visits INT, monthly_revenue DECIMAL, monthly_orders INT)',
  MerchantSummary:
    'CREATE TABLE MerchantSummary (idMerchant INT, total_customers INT, total_revenue DECIMAL, total_visits INT, total_branches INT, total_orders INT, avg_order_value DECIMAL)',
  CustomerSummary:
    'CREATE TABLE CustomerSummary (idMerchant INT, idCustomer INT, customer_name VARCHAR, segment VARCHAR, total_visits INT, total_spend DECIMAL, registration_date DATE, last_visit_date DATE)',
  LoyaltyProgramSummary:
    'CREATE TABLE LoyaltyProgramSummary (idMerchant INT, segment VARCHAR, total_members INT, loyalty_score DECIMAL, points_earned INT, points_redeemed INT)',
  GeographicPerformanceSummary:
    'CREATE TABLE GeographicPerformanceSummary (idMerchant INT, idBranch INT, branch_name VARCHAR, total_visits INT, total_revenue DECIMAL, total_orders INT, avg_order_value DECIMAL)',
  CampaignSummary:
    'CREATE TABLE CampaignSummary (idMerchant INT, campaign_id INT, campaign_name VARCHAR, status VARCHAR, total_sent INT, total_redeemed INT, redemption_rate DECIMAL, revenue_generated DECIMAL)',
  PickupOrderSummary:
    'CREATE TABLE PickupOrderSummary (idMerchant INT, status VARCHAR, total_orders INT, percentage DECIMAL)',
  PaymentAnalyticsSummary:
    'CREATE TABLE PaymentAnalyticsSummary (idMerchant INT, payment_method VARCHAR, channel VARCHAR, total_transactions INT, total_revenue DECIMAL, percentage DECIMAL)',
  POSComparisonSummary:
    'CREATE TABLE POSComparisonSummary (idMerchant INT, product_name VARCHAR, total_sold INT, total_revenue DECIMAL, avg_price DECIMAL)',
};

// ---------------------------------------------------------------------------
// Regex-based table routing patterns (Arabic + English) — ported from Python
// ---------------------------------------------------------------------------

interface TablePattern {
  table: string;
  pattern: RegExp;
}

const TABLE_PATTERNS: TablePattern[] = [
  // ── Daily Performance ──
  {
    table: 'DailyPerformanceSummary',
    pattern:
      /daily|يومي|اليوم|today|yesterday|أمس|البارحة|last\s*\d+\s*days?|آخر\s*\d+\s*[اأ]يام|this\s*week|هذا\s*الأسبوع|الأسبوع\s*الحالي|هالأسبوع|last\s*week|الأسبوع\s*الماضي|الاسبوع\s*الماضي|الأسبوع\s*اللي\s*فات|past\s*week|last\s*7|آخر\s*٧|آخر\s*7|sales?\s*today|مبيعات\s*اليوم|revenue\s*today|إيرادات\s*اليوم|visits?\s*today|زيارات\s*اليوم|orders?\s*today|طلبات\s*اليوم|daily\s*(?:performance|revenue|sales|visits|orders)|أداء\s*يومي|الأداء\s*اليومي|performance\s*(?:today|yesterday)|أداء\s*(?:اليوم|أمس)/i,
  },

  // ── Monthly Performance ──
  {
    table: 'MonthlyPerformanceSummary',
    pattern:
      /monthly|شهري|الشهر|this\s*month|هذا\s*الشهر|الشهر\s*الحالي|last\s*month|الشهر\s*الماضي|الشهر\s*اللي\s*فات|month\s*over\s*month|شهر\s*عن\s*شهر|monthly\s*(?:performance|revenue|sales|visits|orders|trend)|أداء\s*شهري|الأداء\s*الشهري|الإيرادات\s*الشهرية|الطلبات\s*الشهرية|per\s*month|بالشهر|كل\s*شهر|last\s*\d+\s*months?|آخر\s*\d+\s*(?:شهر|أشهر|شهور)|quarterly|ربعي|ربع\s*سنوي|this\s*quarter|last\s*quarter/i,
  },

  // ── Merchant Summary (lifetime / overview) ──
  {
    table: 'MerchantSummary',
    pattern:
      /(?:merchant|store|business)\s*(?:summary|overview|stats|statistics)|ملخص\s*(?:المتجر|المحل|النشاط)|إجمالي|total\s*(?:customers|revenue|visits|orders|sales)|كم\s*(?:عميل|عملاء|زبون|زبائن|إيرادات|زيارات|طلبات)|عدد\s*(?:العملاء|الزبائن|الزيارات|الطلبات|الفروع)|how\s*many\s*(?:customers|branches|orders)|overview|نظرة\s*عامة|لمحة\s*عامة/i,
  },

  // ── Customer Summary ──
  {
    table: 'CustomerSummary',
    pattern:
      /customer|عميل|عملاء|زبون|زبائن|segment|شريحة|شرائح|top\s*(?:customers|spenders|buyers)|أفضل\s*(?:العملاء|الزبائن)|أكثر\s*(?:العملاء|الزبائن)\s*(?:شراء|إنفاق)|customer\s*(?:list|details|info|data|profile)|بيانات\s*(?:العملاء|الزبائن)|قائمة\s*(?:العملاء|الزبائن)|VIP|new\s*customers?|عملاء\s*جدد|زبائن\s*جدد|loyal\s*customers?|عملاء\s*مخلصين|lost\s*customers?|عملاء\s*مفقودين|superFan|سوبر\s*فان|churned?|متراجعين/i,
  },

  // ── Loyalty Program ──
  {
    table: 'LoyaltyProgramSummary',
    pattern:
      /loyalty|ولاء|الولاء|reward|مكافأة|مكافآت|points?|نقاط|نقطة|redemption|استبدال|استرداد|earned|مكتسب|redeemed|مستبدل|loyalty\s*(?:program|score|tier|level)|برنامج\s*(?:الولاء|المكافآت)|membership|عضوية|tier|مستوى|cashback|كاشباك|استرداد\s*نقدي/i,
  },

  // ── Geographic / Branch Performance ──
  {
    table: 'GeographicPerformanceSummary',
    pattern:
      /branch|فرع|فروع|الفرع|الفروع|location|موقع|مواقع|geographic|جغرافي|city|مدينة|مدن|region|منطقة|مناطق|store\s*(?:performance|comparison)|أداء\s*(?:الفرع|الفروع)|مقارنة\s*(?:الفروع|الفرع)|best\s*branch|أفضل\s*فرع|worst\s*branch|أسوأ\s*فرع|branch\s*(?:performance|revenue|sales|comparison)|أداء\s*فرع|Riyadh|Jeddah|Dammam|الرياض|جدة|الدمام/i,
  },

  // ── Campaign ──
  {
    table: 'CampaignSummary',
    pattern:
      /campaign|حملة|حملات|promotion|عرض|عروض|ترويج|marketing|تسويق|offer|coupon|كوبون|كوبونات|قسيمة|discount|خصم|خصومات|campaign\s*(?:performance|stats|results)|أداء\s*(?:الحملة|الحملات)|نتائج\s*(?:الحملة|الحملات)|send|sent|إرسال|مرسل|Ramadan|رمضان/i,
  },

  // ── Pickup Orders ──
  {
    table: 'PickupOrderSummary',
    pattern:
      /pickup|استلام|بيك\s*اب|بيكاب|online\s*order|طلب\s*(?:أونلاين|اون\s*لاين|إلكتروني)|delivery|توصيل|order\s*status|حالة\s*(?:الطلب|الطلبات)|rejected|مرفوض|timeout|منتهي|returned|مسترجع|done|مكتمل|pickup\s*(?:order|performance|stats)|طلبات\s*(?:الاستلام|البيك\s*اب)/i,
  },

  // ── Payment Analytics ──
  {
    table: 'PaymentAnalyticsSummary',
    pattern:
      /payment|دفع|مدفوعات|سداد|card|بطاقة|بطاقات|cash|نقد|نقدي|كاش|digital|رقمي|payment\s*method|طريقة\s*(?:الدفع|السداد)|channel|قناة|قنوات|transaction|معاملة|معاملات|credit\s*card|بطاقة\s*(?:ائتمان|إئتمان)|Apple\s*Pay|STC\s*Pay|Mada|مدى|visa|فيزا|mastercard|ماستركارد/i,
  },

  // ── POS / Product Comparison ──
  {
    table: 'POSComparisonSummary',
    pattern:
      /product|منتج|منتجات|item|صنف|أصناف|menu|قائمة\s*الطعام|قائمة\s*المنتجات|POS|نقطة\s*البيع|best\s*(?:selling|seller)|الأكثر\s*مبيعا|أفضل\s*(?:المنتجات|الأصناف)|top\s*(?:products?|items?|sellers?)|أكثر\s*(?:المنتجات|الأصناف)\s*مبيعا|product\s*(?:performance|comparison|sales)|أداء\s*(?:المنتج|المنتجات)|مقارنة\s*(?:المنتجات|الأصناف)|latte|لاتيه|cappuccino|كابتشينو|coffee|قهوة/i,
  },
];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface SelectTableResult {
  selectedTable: string;
  tableSchema: string;
  fallbackTable?: string;
  fallbackSchema?: string;
}

export function selectTable(
  state: Pick<PipelineState, 'userPrompt' | 'intentCategory'>
): SelectTableResult | null {
  const prompt = state.userPrompt;

  // Layer 1: Deterministic regex matching
  const regexResult = matchByRegex(prompt);
  if (regexResult) {
    console.log(`[selectTable] Regex matched: ${regexResult.selectedTable}`);
    return regexResult;
  }

  // Layer 2: Intent category mapping from semantic model
  if (state.intentCategory) {
    const intentMap = getIntentCategoryMap();
    const table = intentMap[state.intentCategory];
    if (table && MOCK_SCHEMAS[table]) {
      console.log(`[selectTable] Intent category matched: ${table}`);
      return {
        selectedTable: table,
        tableSchema: MOCK_SCHEMAS[table],
      };
    }
  }

  // Layer 3: Semantic router (mock — always null)
  const semanticResult = semanticRouterLookup(prompt);
  if (semanticResult) return semanticResult;

  // Layer 4: Example store (mock — always null)
  const exampleResult = exampleStoreLookup(prompt);
  if (exampleResult) return exampleResult;

  // Layer 5: LLM fallback (mock — always null)
  const llmResult = llmFallbackLookup(prompt);
  if (llmResult) return llmResult;

  // Default: DailyPerformanceSummary
  console.log('[selectTable] No match found, defaulting to DailyPerformanceSummary');
  return {
    selectedTable: 'DailyPerformanceSummary',
    tableSchema: MOCK_SCHEMAS['DailyPerformanceSummary'],
  };
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function matchByRegex(prompt: string): SelectTableResult | null {
  const matches: { table: string; index: number }[] = [];

  for (const { table, pattern } of TABLE_PATTERNS) {
    const match = pattern.exec(prompt);
    if (match) {
      matches.push({ table, index: match.index });
    }
  }

  if (matches.length === 0) return null;

  // If multiple matches, pick the one whose pattern matched earliest in the prompt
  matches.sort((a, b) => a.index - b.index);
  const primaryTable = matches[0].table;
  const fallbackTable = matches.length > 1 ? matches[1].table : undefined;

  return {
    selectedTable: primaryTable,
    tableSchema: MOCK_SCHEMAS[primaryTable] || '',
    fallbackTable,
    fallbackSchema: fallbackTable ? MOCK_SCHEMAS[fallbackTable] : undefined,
  };
}

function getIntentCategoryMap(): Record<string, string> {
  try {
    return getSemanticModel().getIntentCategoryMap();
  } catch {
    // Semantic model YAML not available — return hardcoded defaults
    return {
      daily_performance: 'DailyPerformanceSummary',
      monthly_performance: 'MonthlyPerformanceSummary',
      merchant_overview: 'MerchantSummary',
      customer_analysis: 'CustomerSummary',
      loyalty_program: 'LoyaltyProgramSummary',
      geographic_performance: 'GeographicPerformanceSummary',
      campaign_analysis: 'CampaignSummary',
      pickup_orders: 'PickupOrderSummary',
      payment_analytics: 'PaymentAnalyticsSummary',
      product_comparison: 'POSComparisonSummary',
    };
  }
}

// Mock layers — always return null
function semanticRouterLookup(_prompt: string): SelectTableResult | null {
  return null;
}

function exampleStoreLookup(_prompt: string): SelectTableResult | null {
  return null;
}

function llmFallbackLookup(_prompt: string): SelectTableResult | null {
  return null;
}
