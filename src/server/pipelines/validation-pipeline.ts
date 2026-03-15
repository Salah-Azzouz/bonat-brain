/**
 * Mock validation pipeline — always returns valid.
 *
 * In production, this would validate:
 * - Merchant account status
 * - API rate limits
 * - Feature flags / entitlements
 * - Input sanitization
 */

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export async function runValidationPipeline(
  userPrompt: string,
  merchantId: string
): Promise<ValidationResult> {
  console.log(
    `[validationPipeline] Validating request for merchant=${merchantId}, prompt="${userPrompt.slice(0, 50)}"`
  );

  const errors: string[] = [];
  const warnings: string[] = [];

  // Basic input validation
  if (!userPrompt || userPrompt.trim().length === 0) {
    errors.push('Empty prompt provided');
  }

  if (!merchantId || merchantId.trim().length === 0) {
    errors.push('No merchant ID provided');
  }

  if (userPrompt.length > 2000) {
    warnings.push('Prompt is unusually long and may be truncated');
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}
