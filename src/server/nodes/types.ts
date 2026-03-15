export interface PipelineState {
  userPrompt: string;
  merchantId: string;
  conversationHistory: unknown[];
  history: unknown[];
  confirmedMeaning: string;
  selectedTable: string;
  tableSchema: string;
  validationResult: string;
  dataAvailabilityMessage: string;
  generatedQuery: string;
  executionResult: {
    success: boolean;
    data?: Record<string, unknown>[];
    rowCount?: number;
    columns?: string[];
    error?: string;
    timeout?: boolean;
    partial?: boolean;
    chunks_note?: string;
  };
  errorMessage: string | null;
  retryCount: number;
  currentDate: string;
  currentDayName: string;
  intentCategory?: string;
  fallbackTable?: string;
  fallbackSchema?: string;
  querySource?: 'structured' | 'legacy' | 'fallback';
  scopeWarning?: string;
}
