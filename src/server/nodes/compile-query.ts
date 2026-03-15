/**
 * Deterministic SQL Compiler — Converts QueryIntent to valid MySQL.
 *
 * Guarantees:
 * - All column names are from the allowlist
 * - Merchant isolation is always applied
 * - Date functions are never used (literal dates only)
 * - SQL syntax is always valid
 */

import type { QueryIntent, TimeRange } from './query-schema';
import { getTableMetadata } from './query-schema';

export function compileToSql(
  intent: QueryIntent,
  tableName: string,
  merchantId: string,
  currentDate: string
): { query: string | null; error: string | null; scopeWarning?: string } {
  const allMeta = getTableMetadata();
  const meta = allMeta[tableName];
  if (!meta) {
    return { query: null, error: `Unknown table: ${tableName}` };
  }

  const validColumns = new Set(Object.keys(meta.columns));
  let scopeWarning: string | undefined;

  // Build SELECT clause
  const selectParts: string[] = [];
  let hasAggregation = false;

  for (const m of intent.metrics) {
    if (m.column !== '*') {
      const matched = findColumn(m.column, validColumns);
      if (!matched) {
        return {
          query: null,
          error: `Column \`${m.column}\` does not exist in \`${tableName}\`. Available: ${[...validColumns].sort().join(', ')}`,
        };
      }
      const colName = matched;

      if (m.aggregation && m.aggregation !== 'none') {
        hasAggregation = true;
        const agg = m.aggregation.toUpperCase();
        const alias = m.alias ? ` AS \`${m.alias}\`` : '';
        selectParts.push(`${agg}(\`${colName}\`)${alias}`);
      } else {
        const alias = m.alias ? ` AS \`${m.alias}\`` : '';
        selectParts.push(`\`${colName}\`${alias}`);
      }
    } else {
      if (m.aggregation && m.aggregation !== 'none') {
        hasAggregation = true;
        const agg = m.aggregation.toUpperCase();
        const alias = m.alias ? ` AS \`${m.alias}\`` : '';
        selectParts.push(`${agg}(*)${alias}`);
      } else {
        selectParts.push('*');
      }
    }
  }

  if (!selectParts.length) {
    return { query: null, error: 'No columns specified in metrics' };
  }

  // Add GROUP BY columns to SELECT
  const validatedGroupCols: string[] = [];
  if (intent.group_by) {
    for (const gbCol of intent.group_by) {
      const matched = findColumn(gbCol, validColumns);
      if (!matched) {
        return { query: null, error: `GROUP BY column \`${gbCol}\` does not exist in \`${tableName}\`` };
      }
      validatedGroupCols.push(matched);
      const colBacktick = `\`${matched}\``;
      if (!selectParts.join(' ').includes(colBacktick)) {
        selectParts.unshift(colBacktick);
      }
    }
  }

  const selectClause = selectParts.join(', ');

  // Build WHERE clause
  const whereParts: string[] = [`\`idMerchant\` = ${merchantId}`];

  // Default filters
  const defaultConditions = new Set<string>();
  for (const df of meta.default_filters) {
    whereParts.push(buildCondition(df.column, df.operator, df.value));
    defaultConditions.add(`${df.column.toLowerCase()}|${df.operator}|${df.value}`);
  }

  // User filters
  for (const f of intent.filters) {
    if (f.column.toLowerCase() === 'idmerchant') continue;
    const matched = findColumn(f.column, validColumns);
    if (!matched) {
      console.warn(`[compile_query] Filter column \`${f.column}\` not in ${tableName} — skipping`);
      continue;
    }
    const key = `${matched.toLowerCase()}|${f.operator}|${f.value}`;
    if (defaultConditions.has(key)) continue;
    whereParts.push(buildCondition(matched, f.operator, f.value));
  }

  // Time range
  const timeCol = meta.time_column;
  if (intent.time_range && timeCol) {
    const timeConditions = resolveTimeRange(intent.time_range, timeCol, currentDate);
    whereParts.push(...timeConditions);
  } else if (intent.time_range && !timeCol) {
    scopeWarning =
      `⚠️ DATA SCOPE: The ${tableName} table contains LIFETIME totals only ` +
      `and cannot be filtered to a specific time period. ` +
      `The results below are ALL-TIME data, not limited to the requested dates.`;
  }

  const whereClause = whereParts.join(' AND ');

  // GROUP BY
  let groupByClause = '';
  if (validatedGroupCols.length && hasAggregation) {
    groupByClause = ' GROUP BY ' + validatedGroupCols.map(c => `\`${c}\``).join(', ');
  }

  // ORDER BY
  let orderByClause = '';
  if (intent.order_by) {
    const obCol = intent.order_by.column;
    const matched = findColumn(obCol, validColumns);
    if (matched) {
      const direction = intent.order_by.direction.toUpperCase();
      orderByClause = ` ORDER BY \`${matched}\` ${direction}`;
    } else {
      const aliases = intent.metrics.filter(m => m.alias).map(m => m.alias);
      if (aliases.includes(obCol)) {
        const direction = intent.order_by.direction.toUpperCase();
        orderByClause = ` ORDER BY \`${obCol}\` ${direction}`;
      }
    }
  }

  // LIMIT
  let limitClause = '';
  if (intent.limit) {
    limitClause = ` LIMIT ${Math.min(intent.limit, 100)}`;
  } else {
    limitClause = ' LIMIT 100';
  }

  const query =
    `SELECT ${selectClause} FROM \`${tableName}\` WHERE ${whereClause}${groupByClause}${orderByClause}${limitClause}`;

  console.log(`[compile_query] Compiled SQL: ${query}`);
  return { query, error: null, scopeWarning };
}

// Time resolution

function resolveTimeRange(timeRange: TimeRange, timeColumn: string, currentDateStr: string): string[] {
  const conditions: string[] = [];
  let startStr: string | null = null;
  let endStr: string | null = null;

  if (timeRange.preset) {
    [startStr, endStr] = resolveTimePreset(timeRange.preset, currentDateStr);
  } else if (timeRange.custom_start) {
    startStr = timeRange.custom_start;
    endStr = timeRange.custom_end || currentDateStr;
  }

  if (!startStr) return conditions;

  if (timeColumn === 'year_month') {
    const startD = parseDate(startStr);
    const endD = parseDate(endStr!);

    if (startD.year === endD.year && startD.month === endD.month) {
      conditions.push(`\`year\` = ${startD.year}`);
      conditions.push(`\`month\` = ${startD.month}`);
    } else if (startD.year === endD.year) {
      conditions.push(`\`year\` = ${startD.year}`);
      conditions.push(`\`month\` >= ${startD.month}`);
      conditions.push(`\`month\` <= ${endD.month}`);
    } else {
      conditions.push(
        `(\`year\` > ${startD.year} OR (\`year\` = ${startD.year} AND \`month\` >= ${startD.month}))`
      );
      conditions.push(
        `(\`year\` < ${endD.year} OR (\`year\` = ${endD.year} AND \`month\` <= ${endD.month}))`
      );
    }
  } else {
    const col = `\`${timeColumn}\``;
    if (startStr === endStr) {
      conditions.push(`${col} >= '${startStr}'`);
      conditions.push(`${col} < '${startStr}' + INTERVAL 1 DAY`);
    } else {
      const endD = parseDate(endStr!);
      const nextDay = addDays(endD, 1);
      conditions.push(`${col} >= '${startStr}'`);
      conditions.push(`${col} < '${formatDateObj(nextDay)}'`);
    }
  }

  return conditions;
}

export function resolveTimePreset(preset: string, currentDateStr: string): [string, string] {
  const d = parseDate(currentDateStr);
  const today = new Date(d.year, d.month - 1, d.day);

  switch (preset) {
    case 'today':
      return [currentDateStr, currentDateStr];
    case 'yesterday': {
      const y = addDays(d, -1);
      const yStr = formatDateObj(y);
      return [yStr, yStr];
    }
    case 'last_7_days':
      return [formatDateObj(addDays(d, -7)), currentDateStr];
    case 'this_week': {
      const dow = today.getDay();
      const mondayOffset = dow === 0 ? -6 : 1 - dow;
      const monday = addDays(d, mondayOffset);
      return [formatDateObj(monday), currentDateStr];
    }
    case 'last_week': {
      const dow = today.getDay();
      const mondayOffset = dow === 0 ? -6 : 1 - dow;
      const thisMonday = addDays(d, mondayOffset);
      const lastMonday = addDays(thisMonday, -7);
      const lastSunday = addDays(thisMonday, -1);
      return [formatDateObj(lastMonday), formatDateObj(lastSunday)];
    }
    case 'last_30_days':
      return [formatDateObj(addDays(d, -29)), currentDateStr];
    case 'this_month': {
      const first = { year: d.year, month: d.month, day: 1 };
      return [formatDateObj(first), currentDateStr];
    }
    case 'last_month': {
      const firstOfThis = new Date(d.year, d.month - 1, 1);
      const lastOfPrev = new Date(firstOfThis.getTime() - 86400000);
      const firstOfPrev = new Date(lastOfPrev.getFullYear(), lastOfPrev.getMonth(), 1);
      return [
        formatDate(firstOfPrev),
        formatDate(lastOfPrev),
      ];
    }
    case 'last_3_months': {
      let month = d.month - 3;
      let year = d.year;
      while (month <= 0) { month += 12; year -= 1; }
      return [formatDateObj({ year, month, day: 1 }), currentDateStr];
    }
    case 'last_90_days':
      return [formatDateObj(addDays(d, -89)), currentDateStr];
    case 'this_year':
      return [formatDateObj({ year: d.year, month: 1, day: 1 }), currentDateStr];
    case 'last_year':
      return [
        formatDateObj({ year: d.year - 1, month: 1, day: 1 }),
        formatDateObj({ year: d.year - 1, month: 12, day: 31 }),
      ];
    case 'last_6_months': {
      let month = d.month - 6;
      let year = d.year;
      while (month <= 0) { month += 12; year -= 1; }
      return [formatDateObj({ year, month, day: 1 }), currentDateStr];
    }
    case 'last_14_days':
      return [formatDateObj(addDays(d, -14)), currentDateStr];
    case 'last_12_months':
      return [formatDateObj({ year: d.year - 1, month: d.month, day: 1 }), currentDateStr];
    default:
      console.warn(`[compile_query] Unknown time preset: ${preset} — defaulting to today`);
      return [currentDateStr, currentDateStr];
  }
}

// Helpers

interface DateObj { year: number; month: number; day: number }

function parseDate(s: string): DateObj {
  const [y, m, d] = s.split('-').map(Number);
  return { year: y, month: m, day: d };
}

function addDays(d: DateObj, days: number): DateObj {
  const date = new Date(d.year, d.month - 1, d.day + days);
  return { year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate() };
}

function formatDateObj(d: DateObj): string {
  return `${d.year}-${String(d.month).padStart(2, '0')}-${String(d.day).padStart(2, '0')}`;
}

function formatDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function findColumn(name: string, validColumns: Set<string>): string | null {
  const nameLower = name.toLowerCase();
  for (const col of validColumns) {
    if (col.toLowerCase() === nameLower) return col;
  }
  return null;
}

function isNumeric(value: string): boolean {
  return !isNaN(parseFloat(value)) && isFinite(Number(value));
}

function buildCondition(column: string, operator: string, value: string): string {
  const colRef = `\`${column}\``;

  if (operator === 'in' || operator === 'not_in') {
    const values = value.split(',').map(v => v.trim());
    const valueList = values.every(isNumeric)
      ? values.join(', ')
      : values.map(v => `'${v}'`).join(', ');
    const op = operator === 'in' ? 'IN' : 'NOT IN';
    return `${colRef} ${op} (${valueList})`;
  }

  if (isNumeric(value)) {
    return `${colRef} ${operator} ${value}`;
  }
  return `${colRef} ${operator} '${value}'`;
}
