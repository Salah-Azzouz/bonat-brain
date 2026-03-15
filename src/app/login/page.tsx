'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

const MOCK_USERS: Record<string, string> = {
  'admin@bonat.io': 'admin123',
  'demo@bonat.io': 'demo123',
};

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && localStorage.getItem('token')) {
      router.replace('/chat');
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!email.endsWith('@bonat.io')) {
      setError('Only @bonat.io emails are allowed');
      return;
    }

    setLoading(true);
    await new Promise((r) => setTimeout(r, 500));

    if (MOCK_USERS[email] && MOCK_USERS[email] === password) {
      localStorage.setItem('token', 'mock_' + Date.now());
      localStorage.setItem('user', JSON.stringify({ email, name: email.split('@')[0], merchant_id: 'merchant_1' }));
      router.push('/chat');
    } else {
      setError('Invalid email or password. Try demo@bonat.io / demo123');
    }
    setLoading(false);
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1><span className="brand">Bonat</span> Brain</h1>
        <p className="subtitle">Sign in to your account</p>

        {error && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" placeholder="you@bonat.io" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <span className="form-hint">Must be a @bonat.io email</span>
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div className="auth-footer">
          Don&apos;t have an account? <Link href="/register">Create Account</Link>
        </div>
      </div>
    </div>
  );
}
