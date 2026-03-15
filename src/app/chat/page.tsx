'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';

// ─── Mock Data ────────────────────────────────────────────────────────
const MOCK_RESPONSES: { pattern: RegExp; response: string; suggestions: string[] }[] = [
  {
    pattern: /مبيعات|sales|revenue|إيرادات|today|اليوم/i,
    response: `**Sales Summary — Last 7 Days:**

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
    suggestions: ['Compare with last month', 'Show top products', 'Revenue by branch'],
  },
  {
    pattern: /عملاء|customers?|client/i,
    response: `**Customer Overview:**

- **Total Customers:** 2,847
- **New This Month:** 234
- **Returning:** 1,892 (66.4%)
- **VIP Customers:** 156

| Segment | Count | Avg Spend (SAR) |
|---------|-------|-----------------|
| Super Fan | 156 | 850 |
| Loyal | 423 | 520 |
| Regular | 1,313 | 280 |
| At Risk | 612 | 150 |
| New | 343 | 95 |`,
    suggestions: ['At-risk customers', 'Retention rate', 'Top spenders'],
  },
  {
    pattern: /منتجات|products?|top|best/i,
    response: `**Top 5 Products (Last 30 Days):**

| # | Product | Units | Revenue (SAR) |
|---|---------|-------|---------------|
| 1 | Caramel Macchiato | 1,245 | 24,900 |
| 2 | Iced Latte | 1,102 | 19,836 |
| 3 | Cappuccino | 987 | 14,805 |
| 4 | Chocolate Croissant | 856 | 8,560 |
| 5 | Avocado Toast | 734 | 14,680 |

**Total Units Sold:** 8,924
**Average Order Value:** 45.2 SAR`,
    suggestions: ['Worst performing', 'Product trends', 'Category breakdown'],
  },
  {
    pattern: /فروع|branch|فرع/i,
    response: `**Branch Performance:**

| Branch | Orders | Revenue (SAR) | Rating |
|--------|--------|---------------|--------|
| Riyadh Main | 1,234 | 45,600 | 4.8 |
| Jeddah Mall | 987 | 38,200 | 4.6 |
| Dammam Center | 756 | 28,900 | 4.7 |
| Khobar Plaza | 543 | 21,300 | 4.5 |

**Best:** Riyadh Main
**Fastest Growth:** Dammam Center (+12%)`,
    suggestions: ['Compare branches', 'Branch satisfaction', 'Revenue over time'],
  },
  {
    pattern: /ولاء|loyalty|points|نقاط/i,
    response: `**Loyalty Program Overview:**

- **Active Members:** 1,892
- **Points Issued (Month):** 45,600
- **Points Redeemed:** 23,400 (51.3%)

| Tier | Members | Avg Points |
|------|---------|------------|
| Platinum | 89 | 12,500 |
| Gold | 234 | 6,800 |
| Silver | 567 | 3,200 |
| Bronze | 1,002 | 950 |`,
    suggestions: ['Points expiring', 'Loyalty ROI', 'Inactive members'],
  },
];

const DEFAULT_RESPONSE = {
  response: `I can help you with insights about your business! Try asking about:

- **Sales & Revenue** — daily performance, trends
- **Customers** — segments, retention, top spenders
- **Products** — best sellers, categories
- **Branches** — performance comparison
- **Loyalty Program** — points, tiers, redemption

What would you like to know?`,
  suggestions: ["Show today's sales", 'Customer overview', 'Top products', 'Branch comparison'],
};

function getMockResponse(q: string) {
  for (const m of MOCK_RESPONSES) {
    if (m.pattern.test(q)) return m;
  }
  return DEFAULT_RESPONSE;
}

// ─── Markdown → HTML ──────────────────────────────────────────────────
function formatResponse(text: string): string {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/^- (.+)$/gm, '<li>$1</li>');

  // Tables
  html = html.replace(/(?:^|\n)(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)+)/g, (_, header, _sep, body) => {
    const ths = (header as string).split('|').filter(Boolean).map((c: string) => `<th>${c.trim()}</th>`).join('');
    const rows = (body as string).trim().split('\n').map((row: string) => {
      const tds = row.split('|').filter(Boolean).map((c: string) => `<td>${c.trim()}</td>`).join('');
      return `<tr>${tds}</tr>`;
    }).join('');
    return `<div class="data-table-wrap"><table class="data-table"><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table></div>`;
  });

  html = html.replace(/\n/g, '<br>');
  return html;
}

// ─── Types ────────────────────────────────────────────────────────────
interface Message {
  id: string;
  role: 'user' | 'ai';
  content: string;
  ts: string;
}

// ─── Chat Page ────────────────────────────────────────────────────────
export default function ChatPage() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [toolLabel, setToolLabel] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [lang, setLang] = useState<'ar' | 'en'>('en');
  const [merchant, setMerchant] = useState('merchant_1');
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef(false);

  // Auth guard
  useEffect(() => {
    if (typeof window !== 'undefined' && !localStorage.getItem('token')) {
      router.replace('/login');
    }
  }, [router]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, toolLabel]);

  const send = useCallback((query: string) => {
    if (!query.trim() || streaming) return;
    abortRef.current = false;
    setSuggestions([]);

    const userMsg: Message = { id: `u${Date.now()}`, role: 'user', content: query, ts: new Date().toISOString() };
    const aiId = `a${Date.now()}`;
    const aiMsg: Message = { id: aiId, role: 'ai', content: '', ts: new Date().toISOString() };

    setMessages((p) => [...p, userMsg, aiMsg]);
    setStreaming(true);
    setInput('');

    const { response, suggestions: sug } = getMockResponse(query);

    setToolLabel('Querying database...');

    setTimeout(() => {
      if (abortRef.current) return;
      setToolLabel('Generating response...');

      let idx = 0;
      const interval = setInterval(() => {
        if (abortRef.current) { clearInterval(interval); setStreaming(false); setToolLabel(''); return; }
        idx += 4;
        const partial = response.slice(0, idx);
        setMessages((p) => p.map((m) => (m.id === aiId ? { ...m, content: partial } : m)));

        if (idx >= response.length) {
          clearInterval(interval);
          setStreaming(false);
          setToolLabel('');
          setSuggestions(sug);
        }
      }, 12);
    }, 1000);
  }, [streaming]);

  const stop = () => { abortRef.current = true; setStreaming(false); setToolLabel(''); };

  const clear = () => { setMessages([]); setSuggestions([]); };

  const logout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    router.push('/login');
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); }
  };

  const dir = lang === 'ar' ? 'rtl' : 'ltr';

  return (
    <div className="chat-page" dir={dir}>
      <div className="chat-card">
        {/* Header */}
        <div className="chat-header">
          <h3><span className="brand">Bonat</span> Brain</h3>
          <div className="header-actions">
            <select className="merchant-select" value={merchant} onChange={(e) => setMerchant(e.target.value)}>
              <option value="merchant_1">Merchant 1</option>
              <option value="merchant_2">Merchant 2</option>
              <option value="merchant_3">Merchant 3</option>
            </select>
            <button className="btn-sm" onClick={() => setLang(lang === 'ar' ? 'en' : 'ar')}>
              {lang === 'ar' ? 'EN' : 'AR'}
            </button>
            <button className="btn-sm" onClick={clear}>Clear</button>
            <button className="btn-sm danger" onClick={logout}>Logout</button>
          </div>
        </div>

        {/* Body */}
        <div className="chat-body">
          <div className="chat-messages" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="welcome">
                <div className="welcome-icon">🧠</div>
                <h2>{lang === 'ar' ? 'مرحبا! كيف أقدر أساعدك اليوم؟' : 'Hello! How can I help you today?'}</h2>
                <p>{lang === 'ar' ? 'اسأل عن مبيعاتك، عملائك، أو أي بيانات تجارية' : 'Ask about your sales, customers, or any business data'}</p>
                <div className="welcome-examples">
                  {(lang === 'ar'
                    ? ['كم المبيعات اليوم؟', 'عرض بيانات العملاء', 'أفضل المنتجات', 'مقارنة الفروع']
                    : ["Show today's sales", 'Customer overview', 'Top products this month', 'Compare branches']
                  ).map((q) => (
                    <button key={q} onClick={() => send(q)}>{q}</button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div key={msg.id} className={`message ${msg.role === 'user' ? 'msg-user' : 'msg-ai'}`}>
                <div className="msg-bubble" dangerouslySetInnerHTML={{ __html: msg.role === 'ai' ? formatResponse(msg.content) : msg.content }} />
              </div>
            ))}

            {toolLabel && (
              <div className="progress-bar">
                <div className="dots"><span /><span /><span /></div>
                <span>{toolLabel}</span>
              </div>
            )}

            {suggestions.length > 0 && (
              <div className="suggestions">
                {suggestions.map((s) => (
                  <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            )}
          </div>

          {/* Input */}
          <div className="chat-input">
            <textarea
              rows={1}
              placeholder={lang === 'ar' ? 'اكتب سؤالك هنا...' : 'Type your question...'}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={streaming}
            />
            {streaming ? (
              <button className="btn-send stop" onClick={stop}>&#9632;</button>
            ) : (
              <button className="btn-send" onClick={() => send(input)} disabled={!input.trim()}>&#9654;</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
