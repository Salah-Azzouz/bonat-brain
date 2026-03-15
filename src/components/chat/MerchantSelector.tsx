'use client';

import React from 'react';
import { useMerchant } from '@/hooks/useMerchant';

export default function MerchantSelector() {
  const { merchants, currentMerchant, defaultMerchant, loading, switchMerchant } =
    useMerchant();

  if (merchants.length === 0) return null;

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newId = e.target.value;
    if (newId === currentMerchant) return;

    const confirmed = window.confirm(
      `Switch to Merchant ${newId}?\n\nThis will:\n• Clear your current chat history\n• Start a new session with the selected merchant\n\nContinue?`,
    );

    if (!confirmed) {
      e.target.value = currentMerchant;
      return;
    }

    try {
      await switchMerchant(newId);
      // Reload to clear chat state
      window.location.reload();
    } catch (err) {
      alert(`Failed to switch merchant: ${(err as Error).message}`);
      e.target.value = currentMerchant;
    }
  };

  return (
    <div className="merchant-selector-container">
      <span className="merchant-label">🏪</span>
      <select
        className="merchant-select"
        value={currentMerchant}
        onChange={handleChange}
        disabled={loading}
      >
        {merchants.map((m) => (
          <option key={m} value={m}>
            {m}
            {m === defaultMerchant ? ' (default)' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
