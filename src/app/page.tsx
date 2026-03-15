'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LS_TOKEN_KEY } from '@/lib/constants';

export default function LandingPage() {
  const router = useRouter();
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const token = localStorage.getItem(LS_TOKEN_KEY);
    setIsLoggedIn(!!token);
  }, []);

  if (!mounted) return null;

  return (
    <div className="landing-page">
      {/* Animated background orbs */}
      <div className="landing-orb landing-orb-1" />
      <div className="landing-orb landing-orb-2" />
      <div className="landing-orb landing-orb-3" />

      <div className="landing-content">
        <div className="landing-brain-icon">🧠</div>
        <h1 className="landing-title">
          <span className="brand-logo">Bonat</span> Brain
        </h1>
        <p className="landing-subtitle">AI-Powered Business Analytics</p>

        <div className="landing-actions">
          {isLoggedIn ? (
            <button
              className="auth-button auth-button-primary"
              onClick={() => router.push('/chat')}
            >
              Open Chat
            </button>
          ) : (
            <>
              <button
                className="auth-button auth-button-primary"
                onClick={() => router.push('/login')}
              >
                Login
              </button>
              <button
                className="auth-button auth-button-secondary"
                onClick={() => router.push('/register')}
              >
                Register
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
