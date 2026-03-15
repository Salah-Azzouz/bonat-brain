/**
 * Hallucination detection — full port from Python.
 *
 * Regex-based checks to detect when an LLM response contains
 * fabricated data, invented statistics, or claims not supported
 * by the actual query results.
 *
 * Pure TypeScript, no DB needed.
 */

export interface HallucinationCheck {
  detected: boolean;
  violations: HallucinationViolation[];
  confidence: number;
}

export interface HallucinationViolation {
  type: string;
  description: string;
  evidence: string;
}

// ---------------------------------------------------------------------------
// Patterns that indicate hallucinated content
// ---------------------------------------------------------------------------

const FABRICATED_DATA_PATTERNS: RegExp[] = [
  // Invented specific numbers not in data
  /(?:approximately|about|around|roughly|nearly|almost)\s+[\d,]+(?:\.\d+)?%/i,
  // Hedging language suggesting uncertainty
  /(?:I\s+(?:think|believe|estimate|assume|guess)|it\s+(?:seems?|appears?|looks?\s+like))\s/i,
  // Temporal claims without data support
  /(?:has\s+been\s+(?:steadily|consistently|gradually|rapidly)\s+(?:increasing|decreasing|growing|declining))/i,
  // Prediction language
  /(?:will\s+likely|is\s+expected\s+to|should\s+(?:see|expect)|is\s+projected\s+to)/i,
  // Industry comparison without data
  /(?:compared\s+to\s+(?:industry|market|sector|average|benchmark|competitors?))/i,
  // Generic advice patterns
  /(?:I\s+(?:recommend|suggest|advise)|you\s+(?:should|could|might\s+want\s+to))\s/i,
  // Hypothetical framing
  /\b(?:for example|suppose|let's say|hypothetically|imagine)\b/i,
  // Knowledge disclaimer
  /\b(?:I don't have|cannot access|unable to retrieve|no data available)\b/i,
  // General knowledge framing
  /\b(?:based on (?:my|general) knowledge|typically|usually|on average)\b/i,
];

const INVENTED_ENTITY_PATTERNS: RegExp[] = [
  // Names that weren't in the data
  /(?:customer|employee|manager|staff)\s+(?:named|called)\s+["']?\w+/i,
  // Specific dates not requested
  /(?:on|since|from)\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}/i,
  // Phone numbers
  /(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/,
  // Email addresses
  /[\w.-]+@[\w.-]+\.\w{2,}/,
];

const UNSUPPORTED_CLAIM_PATTERNS: RegExp[] = [
  // Causal claims
  /(?:this\s+is\s+(?:because|due\s+to|caused\s+by|a\s+result\s+of))/i,
  // Correlation claims
  /(?:there\s+is\s+a\s+(?:strong|clear|significant|notable)\s+(?:correlation|relationship|connection))/i,
  // External factor claims
  /(?:(?:due\s+to|because\s+of)\s+(?:COVID|pandemic|economic|seasonal|weather|holiday))/i,
  // Percentage change without data
  /(?:increased|decreased|grew|declined|dropped|rose|fell)\s+(?:by\s+)?[\d.]+%/i,
];

const SUSPICIOUS_ROUND_NUMBERS = [
  /\b(100|200|500|1000|1500|2000|5000|10000|50000|100000|150000)\b/,
];

// ---------------------------------------------------------------------------
// Main check function
// ---------------------------------------------------------------------------

export function checkForHallucinations(
  llmResponse: string,
  queryData: Record<string, unknown>[] | null,
  tableName?: string
): HallucinationCheck {
  const violations: HallucinationViolation[] = [];

  // Check fabricated data patterns
  for (const pattern of FABRICATED_DATA_PATTERNS) {
    const match = pattern.exec(llmResponse);
    if (match) {
      violations.push({
        type: 'fabricated_data',
        description: 'Response contains hedging or approximation language suggesting fabricated data',
        evidence: match[0],
      });
    }
  }

  // Check invented entity patterns
  for (const pattern of INVENTED_ENTITY_PATTERNS) {
    const match = pattern.exec(llmResponse);
    if (match) {
      violations.push({
        type: 'invented_entity',
        description: 'Response contains references to specific entities not present in the data',
        evidence: match[0],
      });
    }
  }

  // Check unsupported claim patterns
  for (const pattern of UNSUPPORTED_CLAIM_PATTERNS) {
    const match = pattern.exec(llmResponse);
    if (match) {
      violations.push({
        type: 'unsupported_claim',
        description: 'Response makes causal or analytical claims not directly supported by the data',
        evidence: match[0],
      });
    }
  }

  // Check for suspiciously round numbers
  let roundCount = 0;
  for (const pattern of SUSPICIOUS_ROUND_NUMBERS) {
    const matches = llmResponse.match(new RegExp(pattern, 'g'));
    if (matches) roundCount += matches.length;
  }
  if (roundCount >= 3) {
    violations.push({
      type: 'suspicious_numbers',
      description: 'Multiple suspiciously round numbers detected — possible fabrication',
      evidence: `${roundCount} round numbers found`,
    });
  }

  // Cross-reference numbers in response with actual data
  if (queryData && queryData.length > 0) {
    const dataViolations = crossReferenceNumbers(llmResponse, queryData);
    violations.push(...dataViolations);
  }

  // Check for response about wrong table
  if (tableName) {
    const tableViolations = checkTableRelevance(llmResponse, tableName);
    violations.push(...tableViolations);
  }

  const confidence = violations.length === 0 ? 1.0 : Math.max(0, 1.0 - violations.length * 0.15);

  return {
    detected: violations.length > 0,
    violations,
    confidence,
  };
}

// ---------------------------------------------------------------------------
// Legacy API (backward compatible)
// ---------------------------------------------------------------------------

export function detectHallucination(
  text: string,
  _context?: Record<string, unknown>
): [boolean, string] {
  const check = checkForHallucinations(text, null);
  if (check.detected && check.violations.length > 0) {
    return [true, check.violations[0].description];
  }
  return [false, ''];
}

export function sanitizeResponse(text: string, _context?: Record<string, unknown>): string {
  let sanitized = text;
  sanitized = sanitized.replace(/\b(approximately|roughly|around|about)\s+/gi, '');
  sanitized = sanitized.replace(/\b(I think|I believe|It seems like|probably)\b/gi, '');
  return sanitized;
}

export function validateDataResponse(
  response: string,
  queryResult?: Record<string, unknown>[]
): [boolean, string] {
  if (!queryResult || queryResult.length === 0) {
    const hasNumbers = /\d{3,}/.test(response);
    if (hasNumbers) {
      return [false, 'Response contains numbers but no query data was provided'];
    }
  }

  const [isHallucinated, reason] = detectHallucination(response);
  if (isHallucinated) {
    return [false, reason];
  }

  return [true, ''];
}

// ---------------------------------------------------------------------------
// Cross-reference numbers in the LLM response with actual query data
// ---------------------------------------------------------------------------

function crossReferenceNumbers(
  response: string,
  data: Record<string, unknown>[]
): HallucinationViolation[] {
  const violations: HallucinationViolation[] = [];

  // Extract all numbers from the response
  const responseNumbers = extractNumbers(response);

  // Extract all numbers from the data
  const dataNumbers = new Set<number>();
  for (const row of data) {
    for (const value of Object.values(row)) {
      if (typeof value === 'number') {
        dataNumbers.add(value);
        dataNumbers.add(Math.round(value));
        dataNumbers.add(Math.round(value * 100) / 100);
      }
    }
  }

  // Check for large numbers in response that don't appear in data
  for (const num of responseNumbers) {
    if (num > 100 && !isNumberInData(num, dataNumbers)) {
      violations.push({
        type: 'fabricated_number',
        description: `Number ${num} appears in response but not in query results`,
        evidence: String(num),
      });
    }
  }

  return violations;
}

function extractNumbers(text: string): number[] {
  const numbers: number[] = [];
  const matches = text.matchAll(/[\d,]+(?:\.\d+)?/g);
  for (const match of matches) {
    const cleaned = match[0].replace(/,/g, '');
    const num = parseFloat(cleaned);
    if (!isNaN(num)) {
      numbers.push(num);
    }
  }
  return numbers;
}

function isNumberInData(num: number, dataNumbers: Set<number>): boolean {
  if (dataNumbers.has(num)) return true;

  for (const dataNum of dataNumbers) {
    if (dataNum !== 0 && Math.abs(num - dataNum) / Math.abs(dataNum) < 0.01) {
      return true;
    }
  }

  const maxData = Math.max(...dataNumbers, 0);
  if (num <= maxData * dataNumbers.size) {
    return true;
  }

  return false;
}

// ---------------------------------------------------------------------------
// Table relevance check
// ---------------------------------------------------------------------------

function checkTableRelevance(
  response: string,
  tableName: string
): HallucinationViolation[] {
  const violations: HallucinationViolation[] = [];

  const tableTopics: Record<string, RegExp> = {
    DailyPerformanceSummary: /(?:daily|today|yesterday|visits?|revenue|orders?)/i,
    MonthlyPerformanceSummary: /(?:monthly|month|trend)/i,
    CustomerSummary: /(?:customer|segment|spend|visit)/i,
    LoyaltyProgramSummary: /(?:loyalty|points?|reward|redeem|segment)/i,
    CampaignSummary: /(?:campaign|promotion|offer|redemption)/i,
    GeographicPerformanceSummary: /(?:branch|location|geographic|city)/i,
    PickupOrderSummary: /(?:pickup|order|delivery|status)/i,
    PaymentAnalyticsSummary: /(?:payment|card|cash|transaction|channel)/i,
    POSComparisonSummary: /(?:product|item|menu|POS|selling)/i,
    MerchantSummary: /(?:total|overall|summary|merchant)/i,
  };

  const expectedTopic = tableTopics[tableName];
  if (expectedTopic && !expectedTopic.test(response)) {
    violations.push({
      type: 'wrong_topic',
      description: `Response does not appear to discuss topics relevant to ${tableName}`,
      evidence: `Expected topics matching ${tableName} pattern`,
    });
  }

  return violations;
}

// ---------------------------------------------------------------------------
// Utility: strip hallucinated content from response
// ---------------------------------------------------------------------------

export function stripHallucinatedContent(
  response: string,
  check: HallucinationCheck
): string {
  if (!check.detected) return response;

  let cleaned = response;

  for (const violation of check.violations) {
    if (violation.type === 'fabricated_data' || violation.type === 'unsupported_claim') {
      const escapedEvidence = violation.evidence.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const sentencePattern = new RegExp(`[^.!?]*${escapedEvidence}[^.!?]*[.!?]?`, 'gi');
      cleaned = cleaned.replace(sentencePattern, '').trim();
    }
  }

  return cleaned || response;
}
