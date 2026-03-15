/**
 * Parse markdown tables in text and convert to styled HTML tables.
 */
export function parseMarkdownTables(text: string): string {
  const tableRegex =
    /(\|[^\n]+\|[\r\n]+\|[-:\s|]+\|[\r\n]+(?:\|[^\n]+\|[\r\n]+)+)/g;

  return text.replace(tableRegex, (match: string) => {
    const lines = match.trim().split(/[\r\n]+/);
    if (lines.length < 3) return match;

    const headers = lines[0]
      .split('|')
      .map((h) => h.trim())
      .filter(Boolean);

    const rows: string[][] = [];
    for (let i = 2; i < lines.length; i++) {
      const cells = lines[i]
        .split('|')
        .map((c) => c.trim())
        .filter(Boolean);
      if (cells.length > 0) rows.push(cells);
    }

    let html = '<div class="data-table-wrapper"><table class="data-table">';
    html += '<thead><tr>';
    headers.forEach((h) => {
      html += `<th>${h}</th>`;
    });
    html += '</tr></thead><tbody>';
    rows.forEach((row, idx) => {
      html += `<tr class="progressive-row loaded" data-row-index="${idx}">`;
      row.forEach((cell) => {
        html += `<td>${cell}</td>`;
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return `\n${html}\n`;
  });
}

/**
 * Format an AI response string (markdown-ish) into styled HTML.
 */
export function formatAIResponse(text: string): string {
  // 1. Convert markdown tables first
  text = parseMarkdownTables(text);

  // 2. Detect tip / recommendation sections
  const tipHeaders = [
    'something to consider',
    'recommendation',
    'quick thought',
    'tip',
    'key takeaway',
    'next steps',
    'want to explore more\\?',
    'explore further',
  ];

  tipHeaders.forEach((header) => {
    const regex = new RegExp(
      `\\*\\*(${header})\\*\\*([\\s\\S]*?)$`,
      'gi',
    );
    text = text.replace(
      regex,
      '{{TIP_SECTION_START}}{{TIP_HEADER:$1}}$2{{TIP_SECTION_END}}',
    );
  });

  // 3. Known section headers
  const sectionHeaders = [
    "monthly overview", "traffic", "customer activity", "sales",
    "sales & revenue", "loyalty", "loyalty program", "revenue",
    "orders", "visits", "this week's activity", "weekly overview", "overview",
  ];

  sectionHeaders.forEach((header) => {
    const regex = new RegExp(`\\*\\*(${header})\\*\\*`, 'gi');
    text = text.replace(regex, '{{SECTION_HEADER:$1}}');
  });

  // Bold text on its own line → section header
  text = text.replace(/^\*\*([^*]+)\*\*$/gm, '{{SECTION_HEADER:$1}}');

  // 4. Markdown → HTML
  let formatted = text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/^#### (.*$)/gm, '<h5>$1</h5>')
    .replace(/^### (.*$)/gm, '<h4>$1</h4>')
    .replace(/^## (.*$)/gm, '<h3>$1</h3>')
    .replace(/^# (.*$)/gm, '<h2 class="insights-title">$1</h2>')
    .replace(/^- (.*$)/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*<\/li>)/, '<ul>$1</ul>')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\n/g, '<br>');

  // Remove single-item bullet lists
  formatted = formatted.replace(/<ul>\s*<li>(.*?)<\/li>\s*<\/ul>/g, '$1');

  // Convert placeholders
  formatted = formatted.replace(
    /\{\{SECTION_HEADER:([^}]+)\}\}/g,
    '<div class="insight-section-header">$1</div>',
  );
  formatted = formatted.replace(
    /\{\{TIP_HEADER:([^}]+)\}\}/g,
    '<div class="insight-tip-header">$1</div>',
  );
  formatted = formatted.replace(
    /\{\{TIP_SECTION_START\}\}/g,
    '<div class="insight-tip">',
  );
  formatted = formatted.replace(/\{\{TIP_SECTION_END\}\}/g, '</div>');

  // Cleanup stray <br> inside tip sections
  formatted = formatted.replace(
    /<div class="insight-tip"><br>/g,
    '<div class="insight-tip">',
  );
  formatted = formatted.replace(
    /<div class="insight-tip-header">([^<]+)<\/div><br>/g,
    '<div class="insight-tip-header">$1</div>',
  );

  return formatted;
}

/**
 * Format a number with commas (e.g. 1234567 → "1,234,567").
 */
export function formatNumber(n: number): string {
  return n.toLocaleString('en-US');
}
