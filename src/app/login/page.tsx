'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import LoginForm from '@/components/auth/LoginForm';

export default function LoginPage() {
  const router = useRouter();
  const { token, login, loading } = useAuth();

  useEffect(() => {
    if (!loading && token) {
      router.replace('/chat');
    }
  }, [token, loading, router]);

  const handleLogin = async (email: string, password: string) => {
    await login(email, password);
    router.push('/chat');
  };

  if (loading) return null;
  if (token) return null;

  return (
    <div className="auth-body">
      <div className="auth-container">
        <LoginForm onSubmit={handleLogin} />
      </div>
    </div>
  );
}
