import { safeText, sanitizeHref } from '../shared/html.js';

export type MarkdownRenderOptions = {
  citations?: boolean;
  linkifyDocCitations?: (html: string, opts: { enable: boolean }) => string;
};

/** Render inline markdown subset used in Q&A answer/output sections. */
function mdInline(s: string, opts?: MarkdownRenderOptions): string {
  let out = safeText(s);
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, text, href) => {
    const safeHref = sanitizeHref(href);
    return `<a href="${safeHref}" target="_blank" rel="noopener">${text}</a>`;
  });
  if (opts?.linkifyDocCitations) {
    out = opts.linkifyDocCitations(out, { enable: Boolean(opts.citations) });
  }
  return out;
}

/** Parse one markdown table row into trimmed cell values. */
function parseMdTableRow(line: string): string[] | null {
  const raw = String(line ?? '');
  if (!raw.includes('|')) return null;
  const parts = raw.split('|');
  const trimmed = parts.map((part) => part.trim());
  if (trimmed.length >= 2 && trimmed[0] === '') trimmed.shift();
  if (trimmed.length >= 2 && trimmed[trimmed.length - 1] === '') trimmed.pop();
  if (!trimmed.length) return null;
  return trimmed;
}

/** Parse markdown table alignment row into per-column alignment tokens. */
function parseMdTableAlign(line: string): string[] | null {
  const cells = parseMdTableRow(line);
  if (!cells || !cells.length) return null;
  const aligns: string[] = [];
  for (const cell of cells) {
    const stripped = String(cell || '').replace(/\s+/g, '');
    if (!/^:?-{3,}:?$/.test(stripped)) return null;
    const left = stripped.startsWith(':');
    const right = stripped.endsWith(':');
    aligns.push(left && right ? 'center' : right ? 'right' : 'left');
  }
  return aligns;
}

/** Render constrained markdown to safe HTML for app display panes. */
export function renderMarkdown(md: string, opts?: MarkdownRenderOptions): string {
  const lines = String(md ?? '').replace(/\r\n/g, '\n').split('\n');
  let html = '';
  let inCode = false;
  let inList = false;
  let codeBuffer = '';

  const closeList = (): void => {
    if (!inList) return;
    html += '</ul>';
    inList = false;
  };

  const flushCode = (): void => {
    if (!codeBuffer) return;
    html += `<pre><code>${safeText(codeBuffer)}</code></pre>`;
    codeBuffer = '';
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const fence = line.match(/^```/);
    if (fence) {
      if (!inCode) {
        closeList();
        inCode = true;
        codeBuffer = '';
      } else {
        inCode = false;
        flushCode();
      }
      continue;
    }

    if (inCode) {
      codeBuffer += line + '\n';
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${mdInline(heading[2], opts)}</h${level}>`;
      continue;
    }

    const thematicBreak = line.trim().match(/^([-*_])(?:\s*\1){2,}$/);
    if (thematicBreak) {
      closeList();
      html += '<hr />';
      continue;
    }

    const maybeHeader = parseMdTableRow(line);
    const aligns = parseMdTableAlign(lines[i + 1]);
    if (maybeHeader && aligns) {
      closeList();
      const headerCells = maybeHeader;
      const colCount = Math.max(headerCells.length, aligns.length);
      const alignAt = (idx: number): string => String(aligns[idx] || 'left');
      const padCells = (cells: string[]): string[] => {
        const out = Array.isArray(cells) ? cells.slice(0, colCount) : [];
        while (out.length < colCount) out.push('');
        return out;
      };
      const renderRow = (cells: string[], tag: string): string => {
        const padded = padCells(cells);
        return padded
          .map((cell, idx) => `<${tag} style="text-align:${alignAt(idx)}">${mdInline(cell, opts)}</${tag}>`)
          .join('');
      };

      let j = i + 2;
      const bodyRows: string[][] = [];
      while (j < lines.length) {
        const rowLine = lines[j];
        if (!String(rowLine || '').trim()) break;
        const row = parseMdTableRow(rowLine);
        if (!row) break;
        bodyRows.push(row);
        j += 1;
      }

      html += `<div class="tableWrap"><table><thead><tr>${renderRow(headerCells, 'th')}</tr></thead><tbody>`;
      for (const row of bodyRows) html += `<tr>${renderRow(row, 'td')}</tr>`;
      html += '</tbody></table></div>';

      i = j - 1;
      continue;
    }

    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) {
      if (!inList) {
        html += '<ul>';
        inList = true;
      }
      html += `<li>${mdInline(li[1], opts)}</li>`;
      continue;
    }

    if (!line.trim()) {
      closeList();
      html += '<br />';
      continue;
    }

    closeList();
    html += `<p>${mdInline(line, opts)}</p>`;
  }

  if (inCode) flushCode();
  if (inList) html += '</ul>';
  return html;
}
