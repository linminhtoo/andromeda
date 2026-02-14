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

/** Manage `[doc=...]` citation targets for the active query context. */
export class CitationManager {
  private targetsByDocId = new Map<string, CitationTarget>();

  /** Reset all known citation targets for the current response context. */
  reset(): void {
    this.targetsByDocId = new Map();
  }

  /** Register first valid citation target per doc from retrieved chunks. */
  updateFromChunks(chunks: any[]): void {
    const list = Array.isArray(chunks) ? chunks : [];
    for (const chunk of list) {
      const docId = String(chunk?.doc_id || '').trim();
      const chunkId = String(chunk?.chunk_id || '').trim();
      const source = String(chunk?.source || '').trim();
      if (!docId || !chunkId || !source) continue;
      if (this.targetsByDocId.has(docId)) continue;
      const label = formatCitationLabelFromChunk(chunk);
      if (!label) continue;
      this.targetsByDocId.set(docId, {
        doc_id: docId,
        chunk_id: chunkId,
        source,
        label,
      });
    }
  }

  /** Return citation metadata for a doc id, if available. */
  get(docId: unknown): CitationTarget | null {
    const key = String(docId || '').trim();
    if (!key) return null;
    return this.targetsByDocId.get(key) || null;
  }

  /** Replace `[doc=...]` markers with clickable links in rendered markdown HTML. */
  linkifyDocCitations(html: string, { enable = false }: { enable?: boolean } = {}): string {
    if (!enable) return html;
    const re = /\[(?:[^\]]*?)\bdoc\s*=\s*([^\]\s]+)(?:[^\]]*?)\]/gi;
    return String(html ?? '').replace(re, (match: string, docIdRaw: string) => {
      const docId = String(docIdRaw || '').trim();
      if (!docId) return match;
      const target = this.targetsByDocId.get(docId);
      if (!target?.label) return match;
      return `<a href="#" class="citationLink" data-doc-id="${escapeHtmlAttr(docId)}" title="${escapeHtmlAttr(docId)}">${safeText(target.label)}</a>`;
    });
  }
}
