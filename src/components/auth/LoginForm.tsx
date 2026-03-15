'use client';

import React, { useState } from 'react';
import Link from 'next/link';

interface LoginFormProps {
  onSubmit: (email: string, password: string) => Promise<void>;
  error?: string;
}

export default function LoginForm({ onSubmit, error: externalError }: LoginFormProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(externalError || '');
  const [loading, setLoading] = useState(false);

  const validate = (): string | null => {
    if (!email) return 'Email is required';
    if (!email.endsWith('@bonat.io')) return 'Only @bonat.io emails are allowed';
    if (!password) return 'Password is required';
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      await onSubmit(email, password);
    } catch (err) {
      setError((err as Error).message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-card">
      <div className="auth-header">
        <h1 className="auth-title">
          <span className="brand-logo">Bonat</span> Brain
        </h1>
        <p className="auth-subtitle">Sign in to your account</p>
      </div>

      <div className="auth-body-content">
        {error && (
          <div className="auth-alert auth-alert-error">
            ⚠️ {error}
          </div>
        )}

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              className="auth-input"
              type="email"
              placeholder="you@bonat.io"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
            <span className="form-hint">Must be a @bonat.io email</span>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              className="auth-input"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          <button
            type="submit"
            className={`auth-button auth-button-primary${loading ? ' auth-button-loading' : ''}`}
            disabled={loading}
          >
            {loading ? '' : 'Sign In'}
          </button>
        </form>

        <div className="auth-footer">
          <p className="auth-footer-text">Don&apos;t have an account?</p>
          <Link href="/register" className="auth-link">
            Create Account
          </Link>
        </div>
      </div>
    </div>
  );
}
