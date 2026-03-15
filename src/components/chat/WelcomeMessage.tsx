'use client';

import React from 'react';
import { Language } from '@/lib/constants';

interface WelcomeMessageProps {
  language: Language;
}

export default function WelcomeMessage({ language }: WelcomeMessageProps) {
  const isArabic = language === 'ar';

  return (
    <div className="welcome-message" dir={isArabic ? 'rtl' : 'ltr'}>
      <div className="welcome-icon">🧠</div>
      <div className="welcome-text">
        {isArabic ? (
          <>
            <p>مرحباً! أنا محلل بياناتك الذكي.</p>
            <p>اسألني أي شيء وراح أجيب لك التحليلات.</p>
            <div className="welcome-examples">
              <p><strong>أمثلة:</strong></p>
              <ul>
                <li>كم عدد الطلبات هذا الشهر؟</li>
                <li>وش أكثر المنتجات مبيعاً؟</li>
                <li>قارن مبيعات هذا الأسبوع بالأسبوع الماضي</li>
              </ul>
            </div>
          </>
        ) : (
          <>
            <p>Hello! I&apos;m your AI data analyst.</p>
            <p>Ask me anything and I&apos;ll get your insights.</p>
            <div className="welcome-examples">
              <p><strong>Examples:</strong></p>
              <ul>
                <li>How many orders this month?</li>
                <li>What are the top selling products?</li>
                <li>Compare this week&apos;s sales to last week</li>
              </ul>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
