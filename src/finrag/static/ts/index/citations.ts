import { escapeHtmlAttr, safeText } from '../shared/html.js';

export type CitationTarget = {
  doc_id: string;
  chunk_id: string;
  source: string;
  label: string;
};

/** Extract normalized document metadata object from a chunk payload. */
export function extractDocMeta(chunk: any): any | null {
  const meta = chunk?.metadata;
  if (!meta || typeof meta !== 'object') return null;
  const doc = meta.doc;
  if (!doc || typeof doc !== 'object') return null;
  return doc;
}

/** Format concise document metadata for chunk/source viewer headers. */
export function formatDocMetaLine(doc: any): string {
  if (!doc || typeof doc !== 'object') return '';
  const bits: string[] = [];
  if (doc.company) bits.push(`Company: ${safeText(doc.company)}`);
  if (doc.ticker) bits.push(`Ticker: ${safeText(doc.ticker)}`);
  const filingBits: string[] = [];
  if (doc.filing_type) filingBits.push(safeText(doc.filing_type));
  if (doc.filing_date) filingBits.push(`filed ${safeText(doc.filing_date)}`);
  if (doc.period_end_date) filingBits.push(`period ended ${safeText(doc.period_end_date)}`);
  if (filingBits.length) bits.push(`Filing: ${filingBits.join(', ')}`);
  if (doc.filing_quarter) bits.push(`Quarter: ${safeText(doc.filing_quarter)}`);
  return bits.join(' • ');
}

/** Normalize filing form values to stable labels used in citation chips. */
function normalizeFilingType(ft: unknown): string {
  const t = String(ft || '').toUpperCase();
  if (!t) return '';
  if (t.includes('10') && t.includes('Q')) return '10Q';
  if (t.includes('10') && t.includes('K')) return '10K';
  return t.replace(/[^A-Z0-9]/g, '');
}

/** Normalize date/quarter strings to `YYYY Qx` when possible. */
function normalizeYearQuarter(v: unknown): string {
  const raw = String(v || '').trim();
  if (!raw) return '';
  const upper = raw.toUpperCase();
  const year = upper.match(/\b(20\d{2})\b/)?.[1] || upper.match(/(20\d{2})/)?.[1] || '';
  const quarter = upper.match(/\bQ([1-4])\b/)?.[1] || upper.match(/Q([1-4])/)?.[1] || '';
  if (year && quarter) return `${year} Q${quarter}`;
  if (year) return year;
  return raw;
}

/** Build a citation display label from chunk-level document metadata. */
export function formatCitationLabelFromChunk(chunk: any): string {
  const doc = extractDocMeta(chunk);
  if (!doc) return '';
  const ticker = String(doc.ticker || '').trim().toUpperCase();
  const yq = normalizeYearQuarter(doc.filing_quarter || doc.period_end_date || doc.filing_date);
  const form = normalizeFilingType(doc.filing_type);
  if (ticker && yq && form) return `${ticker} ${yq} ${form}`;
  return '';
}

/** Parse one citation key value (e.g., `doc=...`, `chunk=...`) from citation marker text. */
function citationValue(raw: unknown, key: 'doc' | 'chunk'): string {
  const text = String(raw || '');
  const re = new RegExp(`\\b${key}\\s*=\\s*([^\\s,\\]]+)`, 'i');
  const value = text.match(re)?.[1] || '';
  return String(value || '').trim();
}

/** Generate a safe fallback label when structured filing metadata is unavailable. */
function fallbackCitationLabel(docId: string): string {
  const doc = String(docId || '').trim();
  if (!doc) return 'citation';
  const short = doc.length > 14 ? `${doc.slice(0, 14)}...` : doc;
  return `doc ${short}`;
}

/** Manage `[doc=...]`/`[doc=... chunk=...]` citation targets for active query context. */
export class CitationManager {
  private targetsByDocId = new Map<string, CitationTarget>();
  private targetsByChunkId = new Map<string, CitationTarget>();

  /** Reset all known citation targets for the current response context. */
  reset(): void {
    this.targetsByDocId = new Map();
    this.targetsByChunkId = new Map();
  }

  /** Register citation targets from retrieved/reranked chunks. */
  updateFromChunks(chunks: any[]): void {
    const list = Array.isArray(chunks) ? chunks : [];
    for (const chunk of list) {
      const docId = String(chunk?.doc_id || '').trim();
      const chunkId = String(chunk?.chunk_id || '').trim();
      const source = String(chunk?.source || '').trim();
      if (!docId || !chunkId || !source) continue;
      const label = formatCitationLabelFromChunk(chunk) || fallbackCitationLabel(docId);
      const target: CitationTarget = {
        doc_id: docId,
        chunk_id: chunkId,
        source,
        label,
      };
      if (!this.targetsByChunkId.has(chunkId)) this.targetsByChunkId.set(chunkId, target);
      if (!this.targetsByDocId.has(docId)) this.targetsByDocId.set(docId, target);
    }
  }

  /** Return citation metadata for a chunk/doc id pair, if available. */
  get(docId: unknown, chunkId: unknown = ''): CitationTarget | null {
    const chunkKey = String(chunkId || '').trim();
    if (chunkKey) {
      const fromChunk = this.targetsByChunkId.get(chunkKey);
      if (fromChunk) return fromChunk;
    }
    const docKey = String(docId || '').trim();
    if (!docKey) return null;
    return this.targetsByDocId.get(docKey) || null;
  }

  /** Replace citation markers with clickable links in rendered markdown HTML. */
  linkifyDocCitations(html: string, { enable = false }: { enable?: boolean } = {}): string {
    if (!enable) return html;
    const re = /\[([^\]]*?\bdoc\s*=\s*[^\]]+?)\]/gi;
    const withDocLinks = String(html ?? '').replace(re, (match: string, bodyRaw: string) => {
      const body = String(bodyRaw || '');
      const docId = citationValue(body, 'doc');
      const citedChunkId = citationValue(body, 'chunk');
      if (!docId) return match;
      const target = this.get(docId, citedChunkId);
      if (!target?.label) return match;
      const chunkId = citedChunkId || target.chunk_id;
      return `<a href="#" class="citationLink" data-doc-id="${escapeHtmlAttr(docId)}" data-chunk-id="${escapeHtmlAttr(chunkId)}" title="${escapeHtmlAttr(match)}">${safeText(target.label)}</a>`;
    });
    const toolRe = /\[([^\]]*?\btool\s*=\s*[^\]]+?)\]/gi;
    return withDocLinks.replace(toolRe, (match: string, bodyRaw: string) => {
      const body = String(bodyRaw || '');
      const tool = String(body.match(/\btool\s*=\s*([^\s,\]]+)/i)?.[1] || '').trim();
      if (!tool) return match;
      const ticker = String(body.match(/\bticker\s*=\s*([^\s,\]]+)/i)?.[1] || '').trim();
      const status = String(body.match(/\bstatus\s*=\s*([^\s,\]]+)/i)?.[1] || '').trim();
      const label = ticker ? `${tool} · ${ticker}` : tool;
      const suffix = status ? ` (${status})` : '';
      return `<span class="toolCitationChip" title="${escapeHtmlAttr(match)}">${safeText(label + suffix)}</span>`;
    });
  }
}
