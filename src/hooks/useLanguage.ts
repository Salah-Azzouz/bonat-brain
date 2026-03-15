'use client';

import { useCallback, useEffect, useState } from 'react';
import { DEFAULT_LANGUAGE, LS_LANGUAGE_KEY, Language } from '@/lib/constants';

export function useLanguage() {
  const [language, setLanguageState] = useState<Language>(DEFAULT_LANGUAGE);

  useEffect(() => {
    const stored = localStorage.getItem(LS_LANGUAGE_KEY) as Language | null;
    if (stored === 'ar' || stored === 'en') {
      setLanguageState(stored);
    }
  }, []);

  const setLanguage = useCallback((lang: Language) => {
    setLanguageState(lang);
    localStorage.setItem(LS_LANGUAGE_KEY, lang);
  }, []);

  const toggleLanguage = useCallback(() => {
    const next: Language = language === 'ar' ? 'en' : 'ar';
    setLanguage(next);
  }, [language, setLanguage]);

  return { language, setLanguage, toggleLanguage };
}
