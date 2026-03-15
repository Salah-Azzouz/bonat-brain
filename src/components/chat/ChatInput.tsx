'use client';

import React, { useRef, useState } from 'react';
import { Language } from '@/lib/constants';

interface ChatInputProps {
  isStreaming: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
  language: Language;
}

export default function ChatInput({
  isStreaming,
  onSend,
  onStop,
  language,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue('');
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // Auto-resize
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 150)}px`;
  };

  const placeholder =
    language === 'ar'
      ? 'اكتب سؤالك هنا...'
      : 'Type your question here...';

  return (
    <form className="input-group" onSubmit={handleSubmit}>
      <textarea
        ref={textareaRef}
        className="form-control"
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={1}
        disabled={isStreaming}
        dir={language === 'ar' ? 'rtl' : 'ltr'}
      />

      {isStreaming ? (
        <button
          type="button"
          className="btn-stop-icon"
          onClick={onStop}
          title="Stop generating"
        >
          ⏹
        </button>
      ) : (
        <button
          type="submit"
          className="btn-send-icon"
          disabled={!value.trim()}
          title="Send"
        >
          ➤
        </button>
      )}
    </form>
  );
}
