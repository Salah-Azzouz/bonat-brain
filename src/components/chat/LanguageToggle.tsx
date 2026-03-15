'use client';

import React from 'react';
import { Language } from '@/lib/constants';

interface LanguageToggleProps {
  language: Language;
  onToggle: () => void;
}

export default function LanguageToggle({ language, onToggle }: LanguageToggleProps) {
  return (
    <button
      className={`btn-lang-toggle ${language === 'ar' ? 'active-ar' : ''}`}
      onClick={onToggle}
      type="button"
      title="Toggle language"
    >
      {language === 'ar' ? 'عربي' : 'EN'}
    </button>
  );
}
