import { API_BASE_URL, LS_TOKEN_KEY } from './constants';

/**
 * Fetch wrapper that automatically attaches the Bearer token from localStorage.
 * Returns the raw Response so callers can handle streaming, JSON, etc.
 */
export async function apiFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token =
    typeof window !== 'undefined' ? localStorage.getItem(LS_TOKEN_KEY) : null;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const url = `${API_BASE_URL}${path}`;

  const response = await fetch(url, {
    ...options,
    headers,
  });

  // Auto-redirect on 401
  if (response.status === 401 && typeof window !== 'undefined') {
    localStorage.removeItem(LS_TOKEN_KEY);
    localStorage.removeItem('user');
    window.location.href = '/login';
  }

  return response;
}

/**
 * Convenience: fetch JSON and return parsed body.
 */
export async function apiJson<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as Record<string, string>).detail || `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}
