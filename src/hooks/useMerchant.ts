'use client';

import { useCallback, useState } from 'react';

const MOCK_MERCHANTS = ['merchant_1', 'merchant_2', 'merchant_3'];

export function useMerchant() {
  const [merchants] = useState<string[]>(MOCK_MERCHANTS);
  const [currentMerchant, setCurrentMerchant] = useState<string>('merchant_1');
  const [loading, setLoading] = useState(false);

  const switchMerchant = useCallback(
    async (merchantId: string) => {
      if (merchantId === currentMerchant) return;
      setLoading(true);
      await new Promise((r) => setTimeout(r, 300));
      setCurrentMerchant(merchantId);
      setLoading(false);
    },
    [currentMerchant],
  );

  return {
    merchants,
    currentMerchant,
    defaultMerchant: 'merchant_1',
    loading,
    switchMerchant,
  };
}
