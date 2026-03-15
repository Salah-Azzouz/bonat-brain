'use client';

import React, { createContext, useCallback, useEffect, useState } from 'react';
import { API_BASE_URL, LS_TOKEN_KEY, LS_USER_KEY } from '@/lib/constants';

export interface User {
  email: string;
  name?: string;
  merchant_id?: string;
  [key: string]: unknown;
}

export interface AuthContextValue {
  token: string | null;
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setToken: (token: string) => void;
  setUser: (user: User) => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Hydrate from localStorage on mount
  useEffect(() => {
    const storedToken = localStorage.getItem(LS_TOKEN_KEY);
    const storedUser = localStorage.getItem(LS_USER_KEY);
    if (storedToken) setTokenState(storedToken);
    if (storedUser) {
      try {
        setUserState(JSON.parse(storedUser));
      } catch {
        // ignore corrupt data
      }
    }
    setLoading(false);
  }, []);

  const setToken = useCallback((t: string) => {
    localStorage.setItem(LS_TOKEN_KEY, t);
    setTokenState(t);
  }, []);

  const setUser = useCallback((u: User) => {
    localStorage.setItem(LS_USER_KEY, JSON.stringify(u));
    setUserState(u);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await fetch(`${API_BASE_URL}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as Record<string, string>).detail || 'Login failed',
        );
      }

      const data = await res.json();
      setToken(data.access_token);
      setUser(data.user);
    },
    [setToken, setUser],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(LS_TOKEN_KEY);
    localStorage.removeItem(LS_USER_KEY);
    setTokenState(null);
    setUserState(null);
    window.location.href = '/login';
  }, []);

  return (
    <AuthContext.Provider
      value={{ token, user, loading, login, logout, setToken, setUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}
