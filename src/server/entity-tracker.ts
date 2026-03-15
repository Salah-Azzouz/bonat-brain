/**
 * Entity extraction from user prompts — full port from Python.
 *
 * Extracts:
 * - Branches (Arabic + English names)
 * - Metrics (revenue, visits, orders, etc.)
 * - Segments (loyalty tiers)
 * - Time references (dates, periods)
 * - Numeric references (top N, counts)
 * - Comparison references
 *
 * Pure TypeScript, no DB needed.
 */

export interface ExtractedEntities {
  branches: string[];
  metrics: string[];
  segments: string[];
  timeReferences: TimeReference[];
  numericReferences: NumericReference[];
  comparisons: ComparisonReference[];
}

export interface TimeReference {
  type: 'preset' | 'relative' | 'absolute' | 'named';
  value: string;
  raw: string;
}

export interface NumericReference {
  type: 'top_n' | 'count' | 'threshold';
  value: number;
  raw: string;
}

export interface ComparisonReference {
  type: 'versus' | 'trend' | 'ranking';
  raw: string;
}

// ---------------------------------------------------------------------------
// Branch patterns (Arabic + English)
// ---------------------------------------------------------------------------

const BRANCH_PATTERNS: Array<{ pattern: RegExp; extract: (m: RegExpMatchArray) => string }> = [
  // English branch names
  {
    pattern: /\b(Riyadh|Jeddah|Dammam|Mecca|Medina|Khobar|Tabuk|Abha|Hail|Jazan)\b/gi,
    extract: (m) => m[1],
  },
  // Arabic city names
  {
    pattern: /(الرياض|جدة|جده|الدمام|مكة|المدينة|الخبر|تبوك|أبها|حائل|جازان|جيزان)/g,
    extract: (m) => m[1],
  },
  // "branch X" pattern
  {
    pattern: /(?:branch|فرع)\s+(?:["']?)(\w[\w\s]*?)(?:["']?)(?:\s|$|,|\.)/gi,
    extract: (m) => m[1].trim(),
  },
  // "فرع ال..." pattern
  {
    pattern: /فرع\s+(ال[\u0600-\u06FF]+)/g,
    extract: (m) => m[1],
  },
];

// ---------------------------------------------------------------------------
// Metric patterns
// ---------------------------------------------------------------------------

const METRIC_PATTERNS: Array<{ pattern: RegExp; metric: string }> = [
  // Revenue
  { pattern: /revenue|إيرادات|إيراد|دخل|مبيعات|sales|مبيع/i, metric: 'revenue' },
  // Visits
  { pattern: /visits?|زيارات?|زياره/i, metric: 'visits' },
  // Orders
  { pattern: /orders?|طلبات?|طلب/i, metric: 'orders' },
  // Customers
  { pattern: /customers?|عملاء|عميل|زبائن|زبون/i, metric: 'customers' },
  // Average order value
  { pattern: /average\s*order\s*value|AOV|متوسط\s*(?:قيمة\s*)?(?:الطلب|الطلبات)/i, metric: 'avg_order_value' },
  // Points
  { pattern: /points?|نقاط|نقطة/i, metric: 'points' },
  // Redemption
  { pattern: /redemption|استبدال|استرداد/i, metric: 'redemption' },
  // New customers
  { pattern: /new\s*customers?|عملاء\s*جدد|زبائن\s*جدد/i, metric: 'new_customers' },
  // Transactions
  { pattern: /transactions?|معاملات?|عمليات?/i, metric: 'transactions' },
  // Growth
  { pattern: /growth|نمو|زيادة/i, metric: 'growth' },
  // Performance
  { pattern: /performance|أداء/i, metric: 'performance' },
];

// ---------------------------------------------------------------------------
// Segment patterns
// ---------------------------------------------------------------------------

const SEGMENT_PATTERNS: Array<{ pattern: RegExp; segment: string }> = [
  { pattern: /superFan|سوبر\s*فان|super\s*fan/i, segment: 'superFan' },
  { pattern: /\bloyal\b|مخلصين|مخلص/i, segment: 'loyal' },
  { pattern: /\bregular\b|منتظمين|منتظم|عاديين/i, segment: 'regular' },
  { pattern: /\bnew\b|جدد|جديد/i, segment: 'new' },
  { pattern: /\blost\b|مفقودين|مفقود|متراجعين|churned?/i, segment: 'lost' },
  { pattern: /\bVIP\b|كبار\s*العملاء/i, segment: 'VIP' },
  { pattern: /\bat[\s_-]?risk\b|معرضين\s*للخسارة/i, segment: 'at_risk' },
];

// ---------------------------------------------------------------------------
// Time reference patterns
// ---------------------------------------------------------------------------

const TIME_PATTERNS: Array<{
  pattern: RegExp;
  type: TimeReference['type'];
  value: string;
}> = [
  // Presets - English
  { pattern: /\btoday\b/i, type: 'preset', value: 'today' },
  { pattern: /\byesterday\b/i, type: 'preset', value: 'yesterday' },
  { pattern: /\bthis\s*week\b/i, type: 'preset', value: 'this_week' },
  { pattern: /\blast\s*week\b/i, type: 'preset', value: 'last_week' },
  { pattern: /\bthis\s*month\b/i, type: 'preset', value: 'this_month' },
  { pattern: /\blast\s*month\b/i, type: 'preset', value: 'last_month' },
  { pattern: /\blast\s*7\s*days?\b/i, type: 'preset', value: 'last_7_days' },
  { pattern: /\blast\s*30\s*days?\b/i, type: 'preset', value: 'last_30_days' },
  { pattern: /\blast\s*90\s*days?\b/i, type: 'preset', value: 'last_90_days' },
  { pattern: /\blast\s*3\s*months?\b/i, type: 'preset', value: 'last_3_months' },
  { pattern: /\bthis\s*year\b/i, type: 'preset', value: 'this_year' },
  { pattern: /\blast\s*year\b/i, type: 'preset', value: 'last_year' },

  // Presets - Arabic
  { pattern: /اليوم/i, type: 'preset', value: 'today' },
  { pattern: /أمس|البارحة/i, type: 'preset', value: 'yesterday' },
  { pattern: /هذا\s*الأسبوع|الأسبوع\s*الحالي|هالأسبوع/i, type: 'preset', value: 'this_week' },
  { pattern: /الأسبوع\s*الماضي|الاسبوع\s*الماضي|الأسبوع\s*اللي\s*فات/i, type: 'preset', value: 'last_week' },
  { pattern: /هذا\s*الشهر|الشهر\s*الحالي/i, type: 'preset', value: 'this_month' },
  { pattern: /الشهر\s*الماضي|الشهر\s*اللي\s*فات/i, type: 'preset', value: 'last_month' },
  { pattern: /آخر\s*٧\s*[اأ]يام|آخر\s*7\s*[اأ]يام/i, type: 'preset', value: 'last_7_days' },
  { pattern: /آخر\s*٣٠\s*يوم|آخر\s*30\s*يوم/i, type: 'preset', value: 'last_30_days' },
  { pattern: /هذه?\s*السنة|السنة\s*الحالية|هذا\s*العام/i, type: 'preset', value: 'this_year' },
  { pattern: /السنة\s*الماضية|العام\s*الماضي/i, type: 'preset', value: 'last_year' },

  // Relative - "last N days/weeks/months"
  { pattern: /\blast\s*(\d+)\s*days?\b/i, type: 'relative', value: 'last_N_days' },
  { pattern: /\blast\s*(\d+)\s*weeks?\b/i, type: 'relative', value: 'last_N_weeks' },
  { pattern: /\blast\s*(\d+)\s*months?\b/i, type: 'relative', value: 'last_N_months' },
  { pattern: /آخر\s*(\d+|[٠-٩]+)\s*(?:يوم|أيام)/i, type: 'relative', value: 'last_N_days' },
  { pattern: /آخر\s*(\d+|[٠-٩]+)\s*(?:أسبوع|أسابيع)/i, type: 'relative', value: 'last_N_weeks' },
  { pattern: /آخر\s*(\d+|[٠-٩]+)\s*(?:شهر|أشهر|شهور)/i, type: 'relative', value: 'last_N_months' },

  // Absolute dates
  { pattern: /\b(\d{4}-\d{2}-\d{2})\b/, type: 'absolute', value: 'date' },

  // Named periods
  { pattern: /\bramadan\b|رمضان/i, type: 'named', value: 'ramadan' },
  { pattern: /\beid\b|عيد/i, type: 'named', value: 'eid' },
  { pattern: /\bjanuary\b|يناير/i, type: 'named', value: 'january' },
  { pattern: /\bfebruary\b|فبراير/i, type: 'named', value: 'february' },
  { pattern: /\bmarch\b|مارس/i, type: 'named', value: 'march' },
  { pattern: /\bapril\b|أبريل|ابريل/i, type: 'named', value: 'april' },
  { pattern: /\bmay\b|مايو/i, type: 'named', value: 'may' },
  { pattern: /\bjune\b|يونيو/i, type: 'named', value: 'june' },
  { pattern: /\bjuly\b|يوليو/i, type: 'named', value: 'july' },
  { pattern: /\baugust\b|أغسطس|اغسطس/i, type: 'named', value: 'august' },
  { pattern: /\bseptember\b|سبتمبر/i, type: 'named', value: 'september' },
  { pattern: /\boctober\b|أكتوبر|اكتوبر/i, type: 'named', value: 'october' },
  { pattern: /\bnovember\b|نوفمبر/i, type: 'named', value: 'november' },
  { pattern: /\bdecember\b|ديسمبر/i, type: 'named', value: 'december' },
];

// ---------------------------------------------------------------------------
// Numeric reference patterns
// ---------------------------------------------------------------------------

const NUMERIC_PATTERNS: Array<{
  pattern: RegExp;
  type: NumericReference['type'];
}> = [
  { pattern: /\btop\s*(\d+)\b/i, type: 'top_n' },
  { pattern: /\bbottom\s*(\d+)\b/i, type: 'top_n' },
  { pattern: /\bbest\s*(\d+)\b/i, type: 'top_n' },
  { pattern: /\bworst\s*(\d+)\b/i, type: 'top_n' },
  { pattern: /أفضل\s*(\d+|[٠-٩]+)/i, type: 'top_n' },
  { pattern: /أسوأ\s*(\d+|[٠-٩]+)/i, type: 'top_n' },
  { pattern: /أعلى\s*(\d+|[٠-٩]+)/i, type: 'top_n' },
  { pattern: /أقل\s*(\d+|[٠-٩]+)/i, type: 'top_n' },
  { pattern: /\bmore\s*than\s*(\d+)\b/i, type: 'threshold' },
  { pattern: /\bless\s*than\s*(\d+)\b/i, type: 'threshold' },
  { pattern: /\bover\s*(\d+)\b/i, type: 'threshold' },
  { pattern: /\bunder\s*(\d+)\b/i, type: 'threshold' },
  { pattern: /أكثر\s*من\s*(\d+|[٠-٩]+)/i, type: 'threshold' },
  { pattern: /أقل\s*من\s*(\d+|[٠-٩]+)/i, type: 'threshold' },
];

// ---------------------------------------------------------------------------
// Comparison patterns
// ---------------------------------------------------------------------------

const COMPARISON_PATTERNS: Array<{
  pattern: RegExp;
  type: ComparisonReference['type'];
}> = [
  { pattern: /\bvs\.?\b|\bversus\b|\bcompare\b|\bcomparison\b/i, type: 'versus' },
  { pattern: /مقارنة|مقابل|ضد/i, type: 'versus' },
  { pattern: /\btrend\b|\bover\s*time\b|\bgrowth\b/i, type: 'trend' },
  { pattern: /توجه|اتجاه|نمو|تطور/i, type: 'trend' },
  { pattern: /\branking\b|\btop\b|\bbest\b|\bworst\b/i, type: 'ranking' },
  { pattern: /ترتيب|أفضل|أسوأ|أعلى|أقل/i, type: 'ranking' },
];

// ---------------------------------------------------------------------------
// Main extraction function
// ---------------------------------------------------------------------------

export function extractEntities(prompt: string): ExtractedEntities {
  return {
    branches: extractBranches(prompt),
    metrics: extractMetrics(prompt),
    segments: extractSegments(prompt),
    timeReferences: extractTimeReferences(prompt),
    numericReferences: extractNumericReferences(prompt),
    comparisons: extractComparisons(prompt),
  };
}

function extractBranches(prompt: string): string[] {
  const branches = new Set<string>();
  for (const { pattern, extract } of BRANCH_PATTERNS) {
    // Reset lastIndex for global patterns
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(prompt)) !== null) {
      branches.add(extract(match));
    }
  }
  return [...branches];
}

function extractMetrics(prompt: string): string[] {
  const metrics = new Set<string>();
  for (const { pattern, metric } of METRIC_PATTERNS) {
    if (pattern.test(prompt)) {
      metrics.add(metric);
    }
  }
  return [...metrics];
}

function extractSegments(prompt: string): string[] {
  const segments = new Set<string>();
  for (const { pattern, segment } of SEGMENT_PATTERNS) {
    if (pattern.test(prompt)) {
      segments.add(segment);
    }
  }
  return [...segments];
}

function extractTimeReferences(prompt: string): TimeReference[] {
  const refs: TimeReference[] = [];
  const seen = new Set<string>();

  for (const { pattern, type, value } of TIME_PATTERNS) {
    pattern.lastIndex = 0;
    const match = pattern.exec(prompt);
    if (match) {
      const key = `${type}:${value}`;
      if (!seen.has(key)) {
        seen.add(key);
        refs.push({ type, value, raw: match[0] });
      }
    }
  }

  return refs;
}

function extractNumericReferences(prompt: string): NumericReference[] {
  const refs: NumericReference[] = [];

  for (const { pattern, type } of NUMERIC_PATTERNS) {
    pattern.lastIndex = 0;
    const match = pattern.exec(prompt);
    if (match) {
      const numStr = match[1];
      const value = parseArabicNumber(numStr);
      if (!isNaN(value)) {
        refs.push({ type, value, raw: match[0] });
      }
    }
  }

  return refs;
}

function extractComparisons(prompt: string): ComparisonReference[] {
  const refs: ComparisonReference[] = [];
  const seen = new Set<string>();

  for (const { pattern, type } of COMPARISON_PATTERNS) {
    const match = pattern.exec(prompt);
    if (match && !seen.has(type)) {
      seen.add(type);
      refs.push({ type, raw: match[0] });
    }
  }

  return refs;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ARABIC_DIGITS: Record<string, string> = {
  '\u0660': '0', '\u0661': '1', '\u0662': '2', '\u0663': '3', '\u0664': '4',
  '\u0665': '5', '\u0666': '6', '\u0667': '7', '\u0668': '8', '\u0669': '9',
};

function parseArabicNumber(str: string): number {
  const western = str.replace(/[٠-٩]/g, (ch) => ARABIC_DIGITS[ch] || ch);
  return parseInt(western, 10);
}
