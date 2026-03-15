import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

interface TableDef {
  description?: string;
  intent_category?: string;
  time_column?: string | null;
  columns?: Record<string, string | { description: string }>;
  default_filters?: Array<{ column: string; operator: string; value: string }>;
  notes?: string;
  routing_examples?: string[];
  column_corrections?: Record<string, string>;
  few_shot_examples?: string;
  column_groups?: Record<string, string[]>;
}

interface RawModel {
  model?: { name?: string; description?: string; timezone?: string; currency?: string };
  tables?: Record<string, TableDef>;
  relationships?: Record<string, unknown>;
  terminology?: Record<string, unknown>;
  verified_queries?: unknown[];
}

export interface TableMetadata {
  columns: Record<string, string>;
  time_column: string | null;
  default_filters: Array<{ column: string; operator: string; value: string }>;
  notes: string;
}

export class SemanticModel {
  private raw: RawModel = {};
  name: string = 'unknown';
  description: string = '';
  timezone: string = 'UTC';
  currency: string = 'USD';

  constructor(yamlPath: string) {
    const fullPath = path.resolve(yamlPath);
    if (!fs.existsSync(fullPath)) {
      throw new Error(`Semantic model not found: ${fullPath}`);
    }
    const content = fs.readFileSync(fullPath, 'utf-8');
    this.raw = yaml.load(content) as RawModel;

    const modelInfo = this.raw.model || {};
    this.name = modelInfo.name || 'unknown';
    this.description = modelInfo.description || '';
    this.timezone = modelInfo.timezone || 'UTC';
    this.currency = modelInfo.currency || 'USD';

    const tableCount = Object.keys(this.raw.tables || {}).length;
    console.log(`[SemanticModel] Loaded '${this.name}' from ${yamlPath} (${tableCount} tables)`);
  }

  getTableMetadata(): Record<string, TableMetadata> {
    const tables = this.raw.tables || {};
    const result: Record<string, TableMetadata> = {};

    for (const [tableName, tableDef] of Object.entries(tables)) {
      const columns: Record<string, string> = {};
      for (const [colName, colInfo] of Object.entries(tableDef.columns || {})) {
        if (typeof colInfo === 'object' && colInfo !== null) {
          columns[colName] = (colInfo as { description: string }).description || '';
        } else {
          columns[colName] = String(colInfo || '');
        }
      }

      let timeColumn = tableDef.time_column;
      if (timeColumn === 'null' || timeColumn === undefined) {
        timeColumn = null;
      }

      result[tableName] = {
        columns,
        time_column: timeColumn as string | null,
        default_filters: tableDef.default_filters || [],
        notes: tableDef.notes || '',
      };
    }
    return result;
  }

  getIntentCategoryMap(): Record<string, string> {
    const tables = this.raw.tables || {};
    const result: Record<string, string> = {};
    for (const [tableName, tableDef] of Object.entries(tables)) {
      if (tableDef.intent_category) {
        result[tableDef.intent_category] = tableName;
      }
    }
    return result;
  }

  getColumnCorrections(tableName?: string): Record<string, Record<string, string>> | Record<string, string> {
    const tables = this.raw.tables || {};
    if (tableName) {
      return { ...(tables[tableName]?.column_corrections || {}) };
    }
    const result: Record<string, Record<string, string>> = {};
    for (const [tname, tdef] of Object.entries(tables)) {
      if (tdef.column_corrections) {
        result[tname] = { ...tdef.column_corrections };
      }
    }
    return result;
  }

  getRoutingExamples(): Record<string, string[]> {
    const tables = this.raw.tables || {};
    const result: Record<string, string[]> = {};
    for (const [tableName, tableDef] of Object.entries(tables)) {
      if (tableDef.routing_examples?.length) {
        result[tableName] = [...tableDef.routing_examples];
      }
    }
    return result;
  }

  getFewShotExamples(tableName?: string): Record<string, string> | string {
    const tables = this.raw.tables || {};
    if (tableName) {
      return tables[tableName]?.few_shot_examples || '';
    }
    const result: Record<string, string> = {};
    for (const [tname, tdef] of Object.entries(tables)) {
      if (tdef.few_shot_examples) {
        result[tname] = tdef.few_shot_examples;
      }
    }
    return result;
  }

  getTableRelationships(): Record<string, unknown> {
    return { ...(this.raw.relationships || {}) };
  }

  getColumnGroups(tableName: string): Record<string, string[]> {
    const tables = this.raw.tables || {};
    return { ...(tables[tableName]?.column_groups || {}) };
  }

  getTerminology(): Record<string, unknown> {
    return this.raw.terminology || {};
  }

  getTableNames(): string[] {
    return Object.keys(this.raw.tables || {});
  }

  getIntentCategories(): string[] {
    return Object.keys(this.getIntentCategoryMap());
  }

  generateIntentDescriptions(): string {
    const tables = this.raw.tables || {};
    const lines: string[] = [];
    for (const [, tableDef] of Object.entries(tables)) {
      const cat = tableDef.intent_category;
      const desc = tableDef.description || '';
      if (cat) {
        const tc = tableDef.time_column;
        const timeNote = tc && tc !== 'null' ? ' (supports date filtering)' : ' (lifetime only)';
        lines.push(`  - ${cat}: ${desc}${timeNote}`);
      }
    }
    return lines.join('\n');
  }

  generateTerminologyPrompt(): string {
    const terminology = this.getTerminology();
    if (!terminology) return '';

    const lines: string[] = ['**Terminology:**'];

    const segments = terminology.segments as Record<string, { name?: string; definition?: string }> | undefined;
    if (segments) {
      lines.push('Loyalty Segments:');
      for (const [segId, segInfo] of Object.entries(segments)) {
        const name = segInfo.name || segId;
        const defn = segInfo.definition || '';
        lines.push(`  - ${name}: ${defn}`);
      }
    }

    const rewardTypes = terminology.reward_types as Record<string, string> | undefined;
    if (rewardTypes) {
      lines.push('Reward Types:');
      for (const [rtype, rdesc] of Object.entries(rewardTypes)) {
        lines.push(`  - ${rtype.charAt(0).toUpperCase() + rtype.slice(1)}: ${rdesc}`);
      }
    }

    return lines.join('\n');
  }

  generateArabicDictionaryPrompt(): string {
    const terminology = this.getTerminology();
    const arabicDict = (terminology.arabic_dictionary || {}) as Record<string, {
      english?: string;
      table?: string;
      notes?: string;
    }>;
    if (!Object.keys(arabicDict).length) return '';

    const lines: string[] = ['**Arabic Dictionary (Arabic → English concept → Table):**'];
    for (const [term, info] of Object.entries(arabicDict)) {
      if (typeof info === 'object' && info !== null) {
        let entry = `  - ${term} → ${info.english || ''}`;
        if (info.table) entry += ` [${info.table}]`;
        if (info.notes) entry += ` — ${info.notes}`;
        lines.push(entry);
      }
    }
    return lines.join('\n');
  }
}

// Singleton
let _semanticModel: SemanticModel | null = null;

const DEFAULT_YAML_PATH = path.join(process.cwd(), 'semantic_models', 'bonat.yaml');
const SEMANTIC_MODEL_PATH = process.env.SEMANTIC_MODEL_PATH || DEFAULT_YAML_PATH;

export function getSemanticModel(): SemanticModel {
  if (!_semanticModel) {
    _semanticModel = new SemanticModel(SEMANTIC_MODEL_PATH);
  }
  return _semanticModel;
}
