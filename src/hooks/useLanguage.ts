'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { DEFAULT_LANGUAGE, LS_LANGUAGE_KEY, Language } from '@/lib/constants';

export function useLanguage() {
  const [language, setLanguageState] = useState<Language>(DEFAULT_LANGUAGE);

  // Hydrate from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(LS_LANGUAGE_KEY) as Language | null;
    if (stored === 'ar' || stored === 'en') {
      setLanguageState(stored);
    }

    // Also try to fetch from backend
    apiFetch('/api/user/preferences')
      .then((res) => {
        if (res.ok) return res.json();
        return null;
      })
      .then((data) => {
        if (data?.preferred_language) {
          const lang = data.preferred_language as Language;
          setLanguageState(lang);
          localStorage.setItem(LS_LANGUAGE_KEY, lang);
        }
      })
      .catch(() => {
        // Ignore — use local value
      });
  }, []);

  const setLanguage = useCallback(async (lang: Language) => {
    setLanguageState(lang);
    localStorage.setItem(LS_LANGUAGE_KEY, lang);

    // Persist to backend
    try {
      await apiFetch('/api/user/preferences', {
        method: 'PATCH',
        body: JSON.stringify({ preferred_language: lang }),
      });
    } catch (e) {
      console.error('Failed to save language preference:', e);
    }
  }, []);

  const toggleLanguage = useCallback(() => {
    const next: Language = language === 'ar' ? 'en' : 'ar';
    setLanguage(next);
  }, [language, setLanguage]);

  return { language, setLanguage, toggleLanguage };
}
