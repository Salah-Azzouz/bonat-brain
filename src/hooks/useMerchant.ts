'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAuth } from './useAuth';

export interface MerchantConfig {
  merchants: string[];
  current: string;
  default: string;
}

export function useMerchant() {
  const { setToken, setUser } = useAuth();
  const [merchants, setMerchants] = useState<string[]>([]);
  const [currentMerchant, setCurrentMerchant] = useState<string>('');
  const [defaultMerchant, setDefaultMerchant] = useState<string>('');
  const [loading, setLoading] = useState(false);

  // Fetch available merchants on mount
  useEffect(() => {
    apiFetch('/api/merchants')
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error('Failed to load merchants');
      })
      .then((data: MerchantConfig) => {
        setMerchants(data.merchants);
        setCurrentMerchant(data.current);
        setDefaultMerchant(data.default);
      })
      .catch((err) => {
        console.error('Error fetching merchants:', err);
      });
  }, []);

  const switchMerchant = useCallback(
    async (merchantId: string) => {
      if (merchantId === currentMerchant) return;

      setLoading(true);
      try {
        const res = await apiFetch('/api/switch-merchant', {
          method: 'POST',
          body: JSON.stringify({ merchant_id: merchantId }),
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            (body as Record<string, string>).detail || 'Failed to switch merchant',
          );
        }

        const data = await res.json();
        setToken(data.access_token);
        setUser(data.user);
        setCurrentMerchant(merchantId);
      } finally {
        setLoading(false);
      }
    },
    [currentMerchant, setToken, setUser],
  );

  return {
    merchants,
    currentMerchant,
    defaultMerchant,
    loading,
    switchMerchant,
  };
}
