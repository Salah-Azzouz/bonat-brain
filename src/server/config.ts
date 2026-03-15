import OpenAI from 'openai';

// Core Configuration
export const SECRET_KEY = process.env.JWT_SECRET_KEY || 'your-secret-key-here-please-change-in-production';
export const ALGORITHM = process.env.JWT_ALGORITHM || 'HS256';
export const ACCESS_TOKEN_EXPIRE_MINUTES = parseInt(process.env.ACCESS_TOKEN_EXPIRE_MINUTES || '480');
export const MAX_HISTORY_TURNS = 5;

// Merchant Configuration
export const ALLOWED_MERCHANTS = ['1032'];
export const DEFAULT_MERCHANT = '1032';

// LLM Configuration
export const LLM_MODEL_NAME = process.env.LLM_MODEL || 'gpt-4.1-mini';

// Query timeout
export const QUERY_TIMEOUT_SECONDS = 30;

// Merchant timezone
export const MERCHANT_TIMEZONE = 'Asia/Riyadh';

export function getMerchantNow(): Date {
  // Return current time in merchant timezone
  const now = new Date();
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: MERCHANT_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const parts = formatter.formatToParts(now);
  const get = (type: string) => parts.find(p => p.type === type)?.value || '0';
  return new Date(
    parseInt(get('year')),
    parseInt(get('month')) - 1,
    parseInt(get('day')),
    parseInt(get('hour')),
    parseInt(get('minute')),
    parseInt(get('second'))
  );
}

export function formatDate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function getDayName(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'long' });
}

// OpenAI client singleton
let _openaiClient: OpenAI | null = null;

export function getOpenAIClient(): OpenAI {
  if (!_openaiClient) {
    _openaiClient = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  }
  return _openaiClient;
}

// Database Configuration
export const DB_CONFIG = {
  host: process.env.DB_HOST,
  database: process.env.DB_DATABASE,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  port: parseInt(process.env.DB_PORT || '3306'),
  connectTimeout: 10000,
};

export const MONGO_CONFIG = {
  host: process.env.MONGO_HOST,
  port: parseInt(process.env.MONGO_PORT || '27017'),
  username: process.env.MONGO_USER,
  password: process.env.MONGO_PASSWORD,
  tls: (process.env.MONGO_TLS || 'true').toLowerCase() === 'true',
};

export const MONGO_DATABASE_NAME = process.env.MONGO_DATABASE;
