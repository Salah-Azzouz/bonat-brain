'use client';

import { useCallback, useRef, useState } from 'react';

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
  timestamp: string;
}

export interface ToolProgress {
  tool: string;
  icon: string;
  title: string;
  description: string;
  status: 'active' | 'completed';
}

export interface UseChatReturn {
  messages: ChatMessage[];
  conversationId: string | null;
  isStreaming: boolean;
  activeTools: ToolProgress[];
  suggestions: string[];
  sendMessage: (query: string, language?: string) => void;
  stopStreaming: () => void;
  clearChat: () => Promise<void>;
  loadHistory: () => Promise<void>;
}

// Mock responses based on keywords
const MOCK_RESPONSES: { pattern: RegExp; response: string; suggestions: string[] }[] = [
  {
    pattern: /مبيعات|sales|revenue|إيرادات/i,
    response: `Here's your sales summary for the last 7 days:

| Day | Orders | Revenue (SAR) |
|-----|--------|---------------|
| Sunday | 45 | 12,350 |
| Monday | 52 | 14,200 |
| Tuesday | 38 | 10,800 |
| Wednesday | 61 | 16,750 |
| Thursday | 55 | 15,300 |
| Friday | 72 | 19,800 |
| Saturday | 68 | 18,500 |

**Total Revenue:** 107,700 SAR
**Average Daily Orders:** 55.9
**Best Day:** Friday with 72 orders`,
    suggestions: ['Compare with last month', 'Show top products', 'Revenue breakdown by branch'],
  },
  {
    pattern: /عملاء|customers|customer/i,
    response: `**Customer Overview:**

- **Total Customers:** 2,847
- **New Customers (This Month):** 234
- **Returning Customers:** 1,892 (66.4%)
- **VIP Customers:** 156

**Customer Segments:**
| Segment | Count | Avg Spend (SAR) |
|---------|-------|-----------------|
| Super Fan | 156 | 850 |
| Loyal | 423 | 520 |
| Regular | 1,313 | 280 |
| At Risk | 612 | 150 |
| New | 343 | 95 |`,
    suggestions: ['Show at-risk customers', 'Customer retention rate', 'Top spending customers'],
  },
  {
    pattern: /منتجات|products|product|top/i,
    response: `**Top 5 Products (Last 30 Days):**

| # | Product | Units Sold | Revenue (SAR) |
|---|---------|------------|---------------|
| 1 | Caramel Macchiato | 1,245 | 24,900 |
| 2 | Iced Latte | 1,102 | 19,836 |
| 3 | Cappuccino | 987 | 14,805 |
| 4 | Chocolate Croissant | 856 | 8,560 |
| 5 | Avocado Toast | 734 | 14,680 |

**Total Products Sold:** 8,924 units
**Average Order Value:** 45.2 SAR`,
    suggestions: ['Show worst performing products', 'Product trends over time', 'Category breakdown'],
  },
  {
    pattern: /فروع|branch|branches|فرع/i,
    response: `**Branch Performance Summary:**

| Branch | Orders | Revenue (SAR) | Avg Rating |
|--------|--------|---------------|------------|
| Riyadh Main | 1,234 | 45,600 | 4.8 |
| Jeddah Mall | 987 | 38,200 | 4.6 |
| Dammam Center | 756 | 28,900 | 4.7 |
| Khobar Plaza | 543 | 21,300 | 4.5 |

**Best Performing:** Riyadh Main
**Highest Growth:** Dammam Center (+12% MoM)`,
    suggestions: ['Compare branches in detail', 'Branch customer satisfaction', 'Revenue by branch over time'],
  },
  {
    pattern: /ولاء|loyalty|points|نقاط/i,
    response: `**Loyalty Program Overview:**

- **Active Members:** 1,892
- **Points Issued (This Month):** 45,600
- **Points Redeemed:** 23,400 (51.3%)
- **Redemption Rate:** 51.3%

**Tier Distribution:**
| Tier | Members | Avg Points |
|------|---------|------------|
| Platinum | 89 | 12,500 |
| Gold | 234 | 6,800 |
| Silver | 567 | 3,200 |
| Bronze | 1,002 | 950 |`,
    suggestions: ['Points expiring soon', 'Loyalty program ROI', 'Inactive members'],
  },
];

const DEFAULT_RESPONSE = {
  response: `I can help you with insights about your business! Try asking about:

- **Sales & Revenue** — daily performance, trends, comparisons
- **Customers** — segments, retention, top spenders
- **Products** — best sellers, categories, trends
- **Branches** — performance comparison, ratings
- **Loyalty Program** — points, tiers, redemption rates

What would you like to know?`,
  suggestions: ['Show today\'s sales', 'Customer overview', 'Top products this month', 'Branch comparison'],
};

function getMockResponse(query: string): { response: string; suggestions: string[] } {
  for (const mock of MOCK_RESPONSES) {
    if (mock.pattern.test(query)) {
      return { response: mock.response, suggestions: mock.suggestions };
    }
  }
  return DEFAULT_RESPONSE;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId] = useState<string | null>('mock_conv_1');
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeTools, setActiveTools] = useState<ToolProgress[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const abortRef = useRef(false);

  const sendMessage = useCallback(
    (query: string) => {
      if (!query.trim() || isStreaming) return;

      setSuggestions([]);
      abortRef.current = false;

      const userMsg: ChatMessage = {
        id: `user_${Date.now()}`,
        role: 'user',
        content: query,
        timestamp: new Date().toISOString(),
      };

      const aiMsgId = `ai_${Date.now()}`;
      const aiMsg: ChatMessage = {
        id: aiMsgId,
        role: 'ai',
        content: '',
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg, aiMsg]);
      setIsStreaming(true);

      const { response, suggestions: mockSuggestions } = getMockResponse(query);

      // Simulate tool usage then streaming
      setActiveTools([
        { tool: 'query_db', icon: '🔍', title: 'Querying database', description: 'Analyzing your data...', status: 'active' },
      ]);

      setTimeout(() => {
        if (abortRef.current) return;
        setActiveTools((prev) =>
          prev.map((t) => (t.tool === 'query_db' ? { ...t, status: 'completed' as const } : t)),
        );
        setActiveTools((prev) => [
          ...prev,
          { tool: 'generating', icon: '✍️', title: 'Generating response', description: '', status: 'active' },
        ]);

        // Stream the response character by character (in chunks)
        let idx = 0;
        const chunkSize = 5;
        const interval = setInterval(() => {
          if (abortRef.current) {
            clearInterval(interval);
            setIsStreaming(false);
            setActiveTools([]);
            return;
          }

          idx += chunkSize;
          const partial = response.slice(0, idx);

          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsgId ? { ...m, content: partial } : m)),
          );

          if (idx >= response.length) {
            clearInterval(interval);
            setIsStreaming(false);
            setActiveTools([]);
            setSuggestions(mockSuggestions);
          }
        }, 15);
      }, 1200);
    },
    [isStreaming],
  );

  const stopStreaming = useCallback(() => {
    abortRef.current = true;
    setIsStreaming(false);
    setActiveTools([]);
  }, []);

  const clearChat = useCallback(async () => {
    setMessages([]);
    setSuggestions([]);
  }, []);

  const loadHistory = useCallback(async () => {
    // No history to load in mock mode
  }, []);

  return {
    messages,
    conversationId,
    isStreaming,
    activeTools,
    suggestions,
    sendMessage,
    stopStreaming,
    clearChat,
    loadHistory,
  };
}
