'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import ChatContainer from '@/components/chat/ChatContainer';

export default function ChatPage() {
  const router = useRouter();
  const { token, loading } = useAuth();

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!loading && !token) {
      router.replace('/login');
    }
  }, [token, loading, router]);

  if (loading) {
    return (
      <div className="chat-loading">
        <div className="loading-dots">
          <span className="dot" />
          <span className="dot" />
          <span className="dot" />
        </div>
      </div>
    );
  }

  if (!token) return null; // will redirect

  return (
    <div className="chat-page">
      <ChatContainer />
    </div>
  );
}
