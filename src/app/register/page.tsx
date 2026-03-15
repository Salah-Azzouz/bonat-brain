'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import RegisterForm from '@/components/auth/RegisterForm';
import { API_BASE_URL } from '@/lib/constants';

export default function RegisterPage() {
  const router = useRouter();
  const { token, loading, setToken, setUser } = useAuth();

  // Redirect if already logged in
  useEffect(() => {
    if (!loading && token) {
      router.replace('/chat');
    }
  }, [token, loading, router]);

  const handleRegister = async (email: string, password: string) => {
    const res = await fetch(`${API_BASE_URL}/api/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(
        (body as Record<string, string>).detail || 'Registration failed',
      );
    }

    const data = await res.json();
    setToken(data.access_token);
    setUser(data.user);
    router.push('/chat');
  };

  if (loading) return null;
  if (token) return null;

  return (
    <div className="auth-body">
      <div className="auth-container">
        <RegisterForm onSubmit={handleRegister} />
      </div>
    </div>
  );
}
