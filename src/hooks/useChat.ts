'use client';

import { useCallback, useRef, useState } from 'react';
import { API_BASE_URL } from '@/lib/constants';
import { apiFetch } from '@/lib/api';
import { useSSE, SSEEvent } from './useSSE';

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
  timestamp: string;
}

export interface ToolProgress {
  tool: string;
  icon: string;
  title: string;
  description: string;
  status: 'active' | 'completed';
}

export interface UseChatReturn {
  messages: ChatMessage[];
  conversationId: string | null;
  isStreaming: boolean;
  activeTools: ToolProgress[];
  suggestions: string[];
  sendMessage: (query: string, language?: string) => void;
  stopStreaming: () => void;
  clearChat: () => Promise<void>;
  loadHistory: () => Promise<void>;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeTools, setActiveTools] = useState<ToolProgress[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // Accumulate tokens into the current AI message
  const fullResponseRef = useRef('');
  const streamingMsgIdRef = useRef<string | null>(null);

  const handleEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case 'token': {
        fullResponseRef.current += event.content as string;
        const msgId = streamingMsgIdRef.current;
        if (msgId) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId ? { ...m, content: fullResponseRef.current } : m,
            ),
          );
        }
        break;
      }

      case 'tool_start':
        setActiveTools((prev) => [
          ...prev,
          {
            tool: event.tool as string,
            icon: (event.icon as string) || '🔧',
            title: (event.title as string) || (event.tool as string),
            description: (event.description as string) || '',
            status: 'active',
          },
        ]);
        break;

      case 'tool_end':
        setActiveTools((prev) =>
          prev.map((t) =>
            t.tool === event.tool ? { ...t, status: 'completed' } : t,
          ),
        );
        break;

      case 'generating_start':
        setActiveTools((prev) => [
          ...prev,
          {
            tool: 'generating',
            icon: (event.icon as string) || '✍️',
            title: (event.title as string) || 'Generating response',
            description: (event.description as string) || '',
            status: 'active',
          },
        ]);
        break;

      case 'done':
        setConversationId((event.conversation_id as string) || null);
        setActiveTools([]);
        setIsStreaming(false);
        if (event.suggestions && Array.isArray(event.suggestions)) {
          setSuggestions(event.suggestions as string[]);
        }
        // Finalize message
        if (streamingMsgIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === streamingMsgIdRef.current
                ? { ...m, content: fullResponseRef.current }
                : m,
            ),
          );
        }
        streamingMsgIdRef.current = null;
        break;

      case 'error':
        setIsStreaming(false);
        setActiveTools([]);
        streamingMsgIdRef.current = null;
        setMessages((prev) => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            role: 'ai',
            content: (event.content as string) || 'An error occurred.',
            timestamp: new Date().toISOString(),
          },
        ]);
        break;
    }
  }, []);

  const handleDone = useCallback(() => {
    setIsStreaming(false);
    setActiveTools([]);
  }, []);

  const handleError = useCallback((err: Error) => {
    setIsStreaming(false);
    setActiveTools([]);
    console.error('SSE error:', err);
  }, []);

  const { start, stop } = useSSE({
    onEvent: handleEvent,
    onDone: handleDone,
    onError: handleError,
  });

  const sendMessage = useCallback(
    (query: string, language?: string) => {
      if (!query.trim()) return;

      // Clear previous suggestions
      setSuggestions([]);

      // Add user message
      const userMsg: ChatMessage = {
        id: `user_${Date.now()}`,
        role: 'user',
        content: query,
        timestamp: new Date().toISOString(),
      };

      // Create placeholder AI message
      const aiMsgId = `ai_${Date.now()}`;
      const aiMsg: ChatMessage = {
        id: aiMsgId,
        role: 'ai',
        content: '',
        timestamp: new Date().toISOString(),
      };

      streamingMsgIdRef.current = aiMsgId;
      fullResponseRef.current = '';

      setMessages((prev) => [...prev, userMsg, aiMsg]);
      setIsStreaming(true);
      setActiveTools([]);

      start(`${API_BASE_URL}/api/chat/agent/stream`, {
        user_query: query,
        conversation_id: conversationId,
        language: language || localStorage.getItem('preferred_language') || 'ar',
      });
    },
    [conversationId, start],
  );

  const stopStreaming = useCallback(() => {
    stop();
    setIsStreaming(false);
    setActiveTools([]);
  }, [stop]);

  const clearChat = useCallback(async () => {
    try {
      await apiFetch('/api/chat/history', { method: 'DELETE' });
    } catch (e) {
      console.error('Failed to clear history:', e);
    }
    setMessages([]);
    setConversationId(null);
    setSuggestions([]);
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const res = await apiFetch('/api/chat/history?limit=20');
      if (!res.ok) return;
      const data = await res.json();

      if (data.messages && data.messages.length > 0) {
        const loaded: ChatMessage[] = [];
        for (const msg of data.messages as Array<{
          user_query: string;
          ai_response: string;
          timestamp: string;
        }>) {
          if (msg.user_query !== '[First chat of the day - Proactive Insights]') {
            loaded.push({
              id: `hist_user_${loaded.length}`,
              role: 'user',
              content: msg.user_query,
              timestamp: msg.timestamp,
            });
          }
          loaded.push({
            id: `hist_ai_${loaded.length}`,
            role: 'ai',
            content: msg.ai_response,
            timestamp: msg.timestamp,
          });
        }
        setMessages(loaded);
        if (data.conversation_id) {
          setConversationId(data.conversation_id);
        }
      }
    } catch (e) {
      console.error('Failed to load history:', e);
    }
  }, []);

  return {
    messages,
    conversationId,
    isStreaming,
    activeTools,
    suggestions,
    sendMessage,
    stopStreaming,
    clearChat,
    loadHistory,
  };
}
