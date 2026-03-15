'use client';

import React, { useEffect, useRef } from 'react';
import { ChatMessage, ToolProgress } from '@/hooks/useChat';
import { Language } from '@/lib/constants';
import MessageBubble from './MessageBubble';
import ProgressTracker from './ProgressTracker';
import SuggestionChips from './SuggestionChips';
import WelcomeMessage from './WelcomeMessage';

interface ChatMessagesProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  activeTools: ToolProgress[];
  suggestions: string[];
  language: Language;
  onSuggestionClick: (text: string) => void;
}

export default function ChatMessages({
  messages,
  isStreaming,
  activeTools,
  suggestions,
  language,
  onSuggestionClick,
}: ChatMessagesProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages or streaming
  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, activeTools]);

  const showWelcome = messages.length === 0;

  return (
    <div className="chat-container" ref={containerRef}>
      {showWelcome && <WelcomeMessage language={language} />}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} isStreaming={isStreaming && msg.id === messages[messages.length - 1]?.id && msg.role === 'ai'} />
      ))}

      {activeTools.length > 0 && <ProgressTracker tools={activeTools} />}

      {!isStreaming && suggestions.length > 0 && (
        <SuggestionChips suggestions={suggestions} onClick={onSuggestionClick} />
      )}
    </div>
  );
}
