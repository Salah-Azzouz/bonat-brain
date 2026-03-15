'use client';

import React, { useEffect } from 'react';
import { useChat } from '@/hooks/useChat';
import { useLanguage } from '@/hooks/useLanguage';
import ChatHeader from './ChatHeader';
import ChatMessages from './ChatMessages';
import ChatInput from './ChatInput';

export default function ChatContainer() {
  const {
    messages,
    isStreaming,
    activeTools,
    suggestions,
    sendMessage,
    stopStreaming,
    clearChat,
    loadHistory,
  } = useChat();

  const { language, toggleLanguage } = useLanguage();

  // Load history on mount
  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSend = (query: string) => {
    sendMessage(query, language);
  };

  return (
    <div className="chat-card">
      <ChatHeader
        language={language}
        onToggleLanguage={toggleLanguage}
        onClearChat={clearChat}
      />

      <div className="chat-body">
        <ChatMessages
          messages={messages}
          isStreaming={isStreaming}
          activeTools={activeTools}
          suggestions={suggestions}
          language={language}
          onSuggestionClick={handleSend}
        />

        <ChatInput
          isStreaming={isStreaming}
          onSend={handleSend}
          onStop={stopStreaming}
          language={language}
        />
      </div>
    </div>
  );
}
