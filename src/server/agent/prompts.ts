/**
 * System Prompt Builder
 *
 * Loads modular rule files from the prompts/ directory and assembles
 * the full system prompt for the main agent.
 */

import fs from 'fs';
import path from 'path';
import { getSemanticModel } from '../semantic-model';

const PROMPTS_DIR = path.join(process.cwd(), 'prompts');

function loadRule(filename: string): string {
  const filePath = path.join(PROMPTS_DIR, filename);
  try {
    return fs.readFileSync(filePath, 'utf-8').trim();
  } catch {
    console.warn(`[Prompts] Rule file not found: ${filePath}`);
    return '';
  }
}

function hasArabic(text: string): boolean {
  return /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/.test(text);
}

export interface BuildSystemPromptParams {
  merchantId: string;
  entityContext: Record<string, unknown>;
  pastInsights: Array<{ content: string; date?: string }>;
  language: string;
  currentDate: string;
  currentDayName?: string;
  userQuery?: string;
}

/**
 * Builds the full system prompt with all rules, context, and terminology.
 * Ported from Python main_agent.py's create_main_agent prompt construction.
 */
export function buildSystemPrompt({
  merchantId,
  entityContext,
  pastInsights,
  language,
  currentDate,
  currentDayName,
  userQuery,
}: BuildSystemPromptParams): string {
  // Load modular rule files
  const toolUsageRules = loadRule('tool_usage.md');
  const routingRules = loadRule('routing_rules.md');
  const dataBoundaryRules = loadRule('data_boundaries.md');
  const antiHallucinationRules = loadRule('anti_hallucination.md');
  const errorHandlingRules = loadRule('error_handling.md');
  const soulRules = loadRule('soul.md').replace('{merchant_id}', merchantId);

  // Build language instruction
  const languageInstruction =
    language === 'ar'
      ? 'Respond in Saudi Arabic (\u0639\u0627\u0645\u064A\u0629 \u0633\u0639\u0648\u062F\u064A\u0629). Use natural Saudi expressions. Numbers + currency in Arabic context.'
      : 'Respond in English. Use SAR for currency.';

  // Day name
  const dayName = currentDayName || new Date(currentDate).toLocaleDateString('en-US', { weekday: 'long' });

  // Generate dynamic sections from semantic model
  const model = getSemanticModel();
  const intentDescriptions = model.generateIntentDescriptions();
  const terminology = model.generateTerminologyPrompt();

  // Inject Arabic dictionary when language is Arabic or text contains Arabic
  let arabicDictionary = '';
  if (language === 'ar' || (userQuery && hasArabic(userQuery))) {
    arabicDictionary = model.generateArabicDictionaryPrompt();
  }

  // Format entity context
  const entityContextStr = formatEntityContext(entityContext);

  // Format past insights
  const pastInsightsStr = formatPastInsights(pastInsights);

  return `${soulRules}

<language>
${languageInstruction}
</language>

<date_context>
Today: ${currentDate} (${dayName}).
Date synonyms (the system resolves dates deterministically \u2014 pass the user\u2019s words directly):
- "last 7 days" = "past week" = 7 days back from today
- "last week" = "previous week" = previous full Mon\u2013Sun
- "last month" = full previous calendar month
- "this week" = Monday of current week to today
- Arabic date expressions \u2014 CRITICAL: pass as "last week", "last month", etc. DO NOT rephrase as "last 7 days":
  - "\u0622\u062E\u0631 \u0623\u0633\u0628\u0648\u0639" / "\u0627\u0644\u0623\u0633\u0628\u0648\u0639 \u0627\u0644\u0645\u0627\u0636\u064A" = "last week" (Mon\u2013Sun calendar week, NOT last 7 days)
  - "\u0622\u062E\u0631 \u0634\u0647\u0631" / "\u0627\u0644\u0634\u0647\u0631 \u0627\u0644\u0645\u0627\u0636\u064A" = "last month"
  - "\u0647\u0630\u0627 \u0627\u0644\u0623\u0633\u0628\u0648\u0639" = "this week"
  - "\u0627\u0644\u064A\u0648\u0645" = "today"
  - "\u0623\u0645\u0633" / "\u0627\u0644\u0628\u0627\u0631\u062D\u0629" = "yesterday"
  - "\u0622\u062E\u0631 \u0667 \u0623\u064A\u0627\u0645" = "last 7 days"
</date_context>

<tools>
You have 4 tools. Call at least one tool on every turn.

Available intent categories for query_db:
${intentDescriptions}

${toolUsageRules}
</tools>

${routingRules}

<platform>
Bonat: Saudi loyalty/CX platform. Merchants manage rewards, track segments, run campaigns.
${terminology}
${arabicDictionary}
System: Dashboard + Mobile App + POS Tablet + Foodics/Retem/Rawa/Dojo integrations.
</platform>

<workflow>
1. Classify: data question \u2192 query_db, knowledge question \u2192 agentic_rag, greeting \u2192 respond_directly.
2. For data: set intent_category, call query_db, then format the response.
3. Use validate only if uncertain about data quality \u2014 optional, at most once.
4. Format: warm, conversational, concise. Use tables or bullet points for data. Currency in SAR.
</workflow>

${errorHandlingRules}

${dataBoundaryRules}

${antiHallucinationRules}

<context>
${entityContextStr}
Reuse resolved dates from context for follow-ups unless user specifies new dates.
</context>

${pastInsightsStr}`;
}

function formatEntityContext(entityContext: Record<string, unknown>): string {
  if (!entityContext || Object.keys(entityContext).length === 0) {
    return 'No prior entity context.';
  }

  const lines: string[] = ['Recent conversation context:'];
  for (const [key, value] of Object.entries(entityContext)) {
    if (value !== null && value !== undefined) {
      lines.push(`  - ${key}: ${JSON.stringify(value)}`);
    }
  }
  return lines.join('\n');
}

function formatPastInsights(insights: Array<{ content: string; date?: string }>): string {
  if (!insights || insights.length === 0) {
    return '';
  }

  const lines: string[] = ['<past_insights>', 'Relevant past insights for this merchant:'];
  for (const insight of insights) {
    const dateStr = insight.date ? ` (${insight.date})` : '';
    lines.push(`  - ${insight.content}${dateStr}`);
  }
  lines.push('</past_insights>');
  return lines.join('\n');
}
