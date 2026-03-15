export interface User {
  user_id: string;
  email: string;
  merchant_id?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export interface SSEEvent {
  type: 'token' | 'tool_start' | 'tool_end' | 'generating_start' | 'done' | 'error';
  content?: string;
  tool?: string;
  icon?: string;
  title?: string;
  description?: string;
  full_response?: string;
  queried_table?: string;
  cost_data?: CostData | null;
}

export interface CostData {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  model: string;
  latency_ms: number;
  llm_calls: number;
  tools_used: string[];
}

export interface Merchant {
  id: string;
  name: string;
}

export interface ChatRequest {
  user_query: string;
  conversation_id?: string;
  language?: string;
}

export interface PipelineState {
  userPrompt: string;
  merchantId: string;
  conversationHistory: Message[];
  history: unknown[];
  confirmedMeaning: string;
  selectedTable: string;
  tableSchema: string;
  validationResult: string;
  dataAvailabilityMessage: string;
  generatedQuery: string;
  executionResult: ExecutionResult;
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

export interface ExecutionResult {
  success: boolean;
  data?: Record<string, unknown>[];
  rowCount?: number;
  columns?: string[];
  error?: string;
  timeout?: boolean;
  partial?: boolean;
  chunks_note?: string;
}
