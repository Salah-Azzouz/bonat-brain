'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import RegisterForm from '@/components/auth/RegisterForm';

export default function RegisterPage() {
  const router = useRouter();
  const { token, loading, register } = useAuth();

  useEffect(() => {
    if (!loading && token) {
      router.replace('/chat');
    }
  }, [token, loading, router]);

  const handleRegister = async (email: string, password: string) => {
    await register(email, password);
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
