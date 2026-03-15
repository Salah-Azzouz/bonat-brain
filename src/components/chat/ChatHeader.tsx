'use client';

import React from 'react';
import { useAuth } from '@/hooks/useAuth';
import MerchantSelector from './MerchantSelector';
import LanguageToggle from './LanguageToggle';
import { Language } from '@/lib/constants';

interface ChatHeaderProps {
  language: Language;
  onToggleLanguage: () => void;
  onClearChat: () => void;
}

export default function ChatHeader({
  language,
  onToggleLanguage,
  onClearChat,
}: ChatHeaderProps) {
  const { logout } = useAuth();

  return (
    <div className="chat-header">
      <div className="chat-header-top">
        <h3>
          <span className="brand-logo">Bonat</span> Brain
        </h3>
      </div>

      <div className="top-actions">
        <MerchantSelector />
        <LanguageToggle language={language} onToggle={onToggleLanguage} />

        <button className="btn-clear-top" onClick={onClearChat} title="Clear chat">
          🗑️ Clear
        </button>

        <button className="btn-logout-top" onClick={logout} title="Logout">
          🚪 Logout
        </button>
      </div>
    </div>
  );
}
