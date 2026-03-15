/**
 * Validates that mock data exists for the given merchant + table combination.
 */

import type { PipelineState } from './types';
import { checkDataExists } from '../db/mysql';

export interface ValidateRequestResult {
  validationResult: string;
  dataAvailabilityMessage: string;
}

export async function validateRequest(state: PipelineState): Promise<ValidateRequestResult> {
  const { selectedTable, merchantId } = state;

  console.log(`[validateRequest] Checking data for merchant=${merchantId}, table=${selectedTable}`);

  try {
    const exists = await checkDataExists(selectedTable, merchantId);

    if (exists) {
      console.log(`[validateRequest] Data available for ${selectedTable}`);
      return {
        validationResult: 'valid',
        dataAvailabilityMessage: '',
      };
    }

    console.log(`[validateRequest] No data found for ${selectedTable}`);
    return {
      validationResult: 'no_data',
      dataAvailabilityMessage: `No data available for table ${selectedTable} and merchant ${merchantId}. This feature may not be set up yet.`,
    };
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    console.error(`[validateRequest] Validation error: ${errorMsg}`);
    return {
      validationResult: 'error',
      dataAvailabilityMessage: `Could not validate data availability: ${errorMsg}`,
    };
  }
}
