// API base URL — uses relative paths so the Next.js proxy or same-origin backend is hit
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || '';

// Default merchant list (fallback when API is unavailable)
export const MERCHANT_LIST = [
  'merchant_1',
  'merchant_2',
  'merchant_3',
];

// LocalStorage keys
export const LS_TOKEN_KEY = 'access_token';
export const LS_USER_KEY = 'user';
export const LS_LANGUAGE_KEY = 'preferred_language';

// Supported languages
export type Language = 'ar' | 'en';
export const DEFAULT_LANGUAGE: Language = 'ar';

// Tool name → display mapping for progress tracker
export const TOOL_DISPLAY_MAP: Record<string, { icon: string; description: string }> = {
  query_database: { icon: '🔍', description: 'Querying database...' },
  analyze_data: { icon: '📊', description: 'Analyzing data...' },
  generate_insights: { icon: '💡', description: 'Generating insights...' },
  fetch_metrics: { icon: '📈', description: 'Fetching metrics...' },
  compare_periods: { icon: '📅', description: 'Comparing time periods...' },
  calculate_kpis: { icon: '🧮', description: 'Calculating KPIs...' },
  generating: { icon: '✍️', description: 'Writing response...' },
};
