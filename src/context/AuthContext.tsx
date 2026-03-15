'use client';

import React, { createContext, useCallback, useEffect, useState } from 'react';
import { LS_TOKEN_KEY, LS_USER_KEY } from '@/lib/constants';

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
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setToken: (token: string) => void;
  setUser: (user: User) => void;
}

// Mock users store (in-memory, resets on refresh)
const MOCK_USERS: Record<string, { password: string; user: User }> = {
  'admin@bonat.io': {
    password: 'admin123',
    user: { email: 'admin@bonat.io', name: 'Admin', merchant_id: 'merchant_1' },
  },
  'demo@bonat.io': {
    password: 'demo123',
    user: { email: 'demo@bonat.io', name: 'Demo User', merchant_id: 'merchant_1' },
  },
};

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem(LS_TOKEN_KEY);
    const storedUser = localStorage.getItem(LS_USER_KEY);
    if (storedToken) setTokenState(storedToken);
    if (storedUser) {
      try {
        setUserState(JSON.parse(storedUser));
      } catch {
        // ignore
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
      // Simulate network delay
      await new Promise((r) => setTimeout(r, 500));

      const entry = MOCK_USERS[email];
      if (!entry || entry.password !== password) {
        throw new Error('Invalid email or password');
      }

      const mockToken = `mock_token_${Date.now()}`;
      setToken(mockToken);
      setUser(entry.user);
    },
    [setToken, setUser],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      await new Promise((r) => setTimeout(r, 500));

      if (!email.endsWith('@bonat.io')) {
        throw new Error('Only @bonat.io emails are allowed');
      }

      if (MOCK_USERS[email]) {
        throw new Error('User already exists');
      }

      const newUser: User = {
        email,
        name: email.split('@')[0],
        merchant_id: 'merchant_1',
      };

      MOCK_USERS[email] = { password, user: newUser };

      const mockToken = `mock_token_${Date.now()}`;
      setToken(mockToken);
      setUser(newUser);
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
      value={{ token, user, loading, login, register, logout, setToken, setUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}
