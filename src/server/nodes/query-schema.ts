import { z } from 'zod';
import { getSemanticModel, type TableMetadata } from '../semantic-model';

// Zod schemas matching the Python Pydantic models

export const MetricSelectionSchema = z.object({
  column: z.string().describe("Column name from the table's available columns, or '*' for COUNT(*)"),
  aggregation: z.enum(['sum', 'count', 'avg', 'max', 'min', 'none']).default('none')
    .describe("Aggregation function. 'none' = raw value. 'count' with column='*' = COUNT(*)."),
  alias: z.string().optional().describe('Optional alias for the result column'),
});

export const FilterConditionSchema = z.object({
  column: z.string().describe('Column name to filter on'),
  operator: z.enum(['=', '!=', '>', '>=', '<', '<=', 'in', 'not_in'])
    .describe('Comparison operator'),
  value: z.string().describe(
    "Filter value. For 'in'/'not_in', comma-separated: 'superFan,loyal'. For dates, use YYYY-MM-DD."
  ),
});

export const OrderBySchema = z.object({
  column: z.string().describe('Column to sort by'),
  direction: z.enum(['asc', 'desc']).default('desc'),
});

export const TimeRangeSchema = z.object({
  preset: z.string().optional().describe(
    "Time preset: 'today', 'yesterday', 'last_7_days', 'this_week', " +
    "'last_week', 'this_month', 'last_month', 'last_30_days', " +
    "'last_3_months', 'last_90_days', 'this_year', 'last_year'"
  ),
  custom_start: z.string().optional().describe('Custom start date YYYY-MM-DD'),
  custom_end: z.string().optional().describe('Custom end date YYYY-MM-DD'),
});

export const QueryIntentSchema = z.object({
  metrics: z.array(MetricSelectionSchema).describe('Columns to select, with optional aggregation'),
  filters: z.array(FilterConditionSchema).default([])
    .describe('WHERE conditions (idMerchant is auto-added — do NOT include it)'),
  group_by: z.array(z.string()).default([])
    .describe('Columns to GROUP BY when using aggregations across groups'),
  order_by: OrderBySchema.optional().describe('Sort order for results'),
  limit: z.number().int().optional().describe("Max rows to return (e.g., 5 for 'top 5')"),
  time_range: TimeRangeSchema.optional().describe('Time range filter. Only for tables with a time column.'),
});

export type QueryIntent = z.infer<typeof QueryIntentSchema>;
export type MetricSelection = z.infer<typeof MetricSelectionSchema>;
export type FilterCondition = z.infer<typeof FilterConditionSchema>;
export type OrderByClause = z.infer<typeof OrderBySchema>;
export type TimeRange = z.infer<typeof TimeRangeSchema>;

// Load TABLE_METADATA from YAML
let _tableMetadata: Record<string, TableMetadata> | null = null;

export function getTableMetadata(): Record<string, TableMetadata> {
  if (!_tableMetadata) {
    _tableMetadata = getSemanticModel().getTableMetadata();
  }
  return _tableMetadata;
}

// Alias for backward compatibility
export const TABLE_METADATA = new Proxy({} as Record<string, TableMetadata>, {
  get(_target, prop: string) {
    return getTableMetadata()[prop];
  },
  has(_target, prop: string) {
    return prop in getTableMetadata();
  },
  ownKeys() {
    return Object.keys(getTableMetadata());
  },
  getOwnPropertyDescriptor(_target, prop: string) {
    const meta = getTableMetadata();
    if (prop in meta) {
      return { configurable: true, enumerable: true, value: meta[prop] };
    }
    return undefined;
  },
});

export function getColumnListForPrompt(tableName: string): string {
  const meta = getTableMetadata()[tableName];
  if (!meta) return '';
  return Object.entries(meta.columns)
    .map(([col, desc]) => `  - \`${col}\`: ${desc}`)
    .join('\n');
}

export function getValidColumns(tableName: string): Set<string> {
  const meta = getTableMetadata()[tableName];
  if (!meta) return new Set();
  return new Set(Object.keys(meta.columns));
}

export function getTableNotes(tableName: string): string {
  const meta = getTableMetadata()[tableName];
  return meta?.notes || '';
}

export function getTimeColumn(tableName: string): string | null {
  const meta = getTableMetadata()[tableName];
  return meta?.time_column || null;
}

export function getTimePresetsForPrompt(): string {
  return `Available time presets (compiler resolves dates automatically):
  - "today": Today only
  - "yesterday": Yesterday only
  - "last_7_days": 7 days counting back from today (includes today)
  - "this_week": Current week from Monday to today
  - "last_week": The PREVIOUS full Monday-to-Sunday week
  - "this_month": First of this month to today
  - "last_month": Full previous calendar month
  - "last_14_days": 14 days counting back from today
  - "last_30_days": 30 days counting back from today (includes today)
  - "last_3_months": From 3 months ago (1st of that month) to today
  - "last_90_days": 90 days counting back from today
  - "this_year": January 1 to today
  - "last_year": Full previous calendar year (Jan 1 → Dec 31)
Or use custom_start / custom_end for specific date ranges (YYYY-MM-DD).

⚠️ IMPORTANT — "last 7 days" ≠ "last week":
  - "last 7 days" / "past week" / "this past week" / "آخر ٧ أيام" → use preset "last_7_days"
  - "last week" / "previous week" / "آخر أسبوع" / "الأسبوع الماضي" → use preset "last_week"
  - "last month" / "آخر شهر" / "الشهر الماضي" → use preset "last_month"`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function buildTableQueryIntentSchema(tableName: string): any {
  const meta = getTableMetadata()[tableName];
  if (!meta) return QueryIntentSchema;

  const columns = Object.keys(meta.columns).sort();
  const columnsWithStar = ['*', ...columns];

  const TableMetricSchema = z.object({
    column: z.enum(columnsWithStar as [string, ...string[]])
      .describe("Column name from the table's available columns, or '*' for COUNT(*)"),
    aggregation: z.enum(['sum', 'count', 'avg', 'max', 'min', 'none']).default('none'),
    alias: z.string().optional(),
  });

  const TableFilterSchema = z.object({
    column: z.enum(columns as [string, ...string[]])
      .describe('Column name to filter on'),
    operator: z.enum(['=', '!=', '>', '>=', '<', '<=', 'in', 'not_in']),
    value: z.string(),
  });

  return z.object({
    metrics: z.array(TableMetricSchema),
    filters: z.array(TableFilterSchema).default([]),
    group_by: z.array(z.string()).default([]),
    order_by: OrderBySchema.optional(),
    limit: z.number().int().optional(),
    time_range: TimeRangeSchema.optional(),
  });
}
