'use client';

import React from 'react';
import { ChatMessage } from '@/hooks/useChat';
import { formatAIResponse } from '@/lib/formatResponse';

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  const formattedTime = new Date(message.timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  const contentHtml =
    isUser
      ? undefined
      : formatAIResponse(message.content || '');

  return (
    <div className={`message ${isUser ? 'user-message' : 'ai-message'}${isStreaming ? ' streaming' : ''}`}>
      <div className="message-content">
        {isUser ? (
          message.content
        ) : (
          <>
            <span dangerouslySetInnerHTML={{ __html: contentHtml! }} />
            {isStreaming && message.content && (
              <span className="cursor-blink">|</span>
            )}
          </>
        )}
      </div>
      <small>{isUser ? 'You' : 'AI Assistant'} &middot; {formattedTime}</small>
    </div>
  );
}
