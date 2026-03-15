'use client';

import { useCallback, useRef } from 'react';
import { LS_TOKEN_KEY } from '@/lib/constants';

export interface SSEEvent {
  type: string;
  [key: string]: unknown;
}

export interface UseSSEOptions {
  /** Called for every parsed SSE event */
  onEvent: (event: SSEEvent) => void;
  /** Called when the stream ends naturally */
  onDone?: () => void;
  /** Called on error (network, parse, etc.) */
  onError?: (error: Error) => void;
}

/**
 * Hook for POST-based Server-Sent Events using fetch + ReadableStream.
 * Returns { start, stop } where start() initiates the stream.
 */
export function useSSE({ onEvent, onDone, onError }: UseSSEOptions) {
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (url: string, body: Record<string, unknown>) => {
      // Abort any in-flight request
      stop();

      const controller = new AbortController();
      abortRef.current = controller;

      const token =
        typeof window !== 'undefined'
          ? localStorage.getItem(LS_TOKEN_KEY)
          : null;

      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!response.ok) {
          if (response.status === 401 && typeof window !== 'undefined') {
            localStorage.removeItem(LS_TOKEN_KEY);
            localStorage.removeItem('user');
            window.location.href = '/login';
            return;
          }
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          const segments = buffer.split('\n\n');
          buffer = segments.pop()!; // keep incomplete segment

          for (const segment of segments) {
            if (segment.startsWith('data: ')) {
              const raw = segment.slice(6);
              if (raw.trim().startsWith(':')) continue; // keepalive

              try {
                const event: SSEEvent = JSON.parse(raw);
                onEvent(event);
              } catch {
                console.error('Failed to parse SSE event:', raw);
              }
            }
          }
        }

        onDone?.();
      } catch (err: unknown) {
        if ((err as Error).name === 'AbortError') {
          // User-initiated cancellation — not an error
          return;
        }
        onError?.(err as Error);
      } finally {
        abortRef.current = null;
      }
    },
    [onEvent, onDone, onError, stop],
  );

  return { start, stop };
}
