import { describe, expect, it } from 'vitest';

import {
  CitationManager,
  extractDocMeta,
  formatCitationLabelFromChunk,
  formatDocMetaLine,
} from '../../src/andromeda/static/ts/index/citations.ts';

describe('citations helpers', () => {
  it('extractDocMeta returns doc object when metadata shape is valid', () => {
    const chunk = { metadata: { doc: { ticker: 'ACME' } } };

    expect(extractDocMeta(chunk)).toEqual({ ticker: 'ACME' });
    expect(extractDocMeta({ metadata: {} })).toBeNull();
    expect(extractDocMeta(null)).toBeNull();
  });

  it('formatDocMetaLine emits expected compact metadata string', () => {
    const line = formatDocMetaLine({
      company: 'Acme <Corp>',
      ticker: 'ACME',
      filing_type: '10-Q',
      filing_date: '2026-01-30',
      period_end_date: '2025-12-31',
      filing_quarter: '2025 Q4',
    });

    expect(line).toContain('Company: Acme &lt;Corp&gt;');
    expect(line).toContain('Ticker: ACME');
    expect(line).toContain('Filing: 10-Q, filed 2026-01-30, period ended 2025-12-31');
    expect(line).toContain('Quarter: 2025 Q4');
  });

  it('formatCitationLabelFromChunk normalizes ticker/quarter/form', () => {
    const chunk = {
      metadata: {
        doc: {
          ticker: 'acme',
          filing_quarter: 'FY2025Q4',
          filing_type: '10-Q/A',
        },
      },
    };

    expect(formatCitationLabelFromChunk(chunk)).toBe('ACME 2025 Q4 10Q');
  });

  it('CitationManager stores first target by doc and all targets by chunk', () => {
    const manager = new CitationManager();
    manager.updateFromChunks([
      {
        doc_id: 'doc-1',
        chunk_id: 'chunk-1',
        source: 'a.md',
        metadata: { doc: { ticker: 'ACME', filing_quarter: '2025 Q4', filing_type: '10-Q' } },
      },
      {
        doc_id: 'doc-1',
        chunk_id: 'chunk-2',
        source: 'a.md',
        metadata: { doc: { ticker: 'ACME', filing_quarter: '2025 Q4', filing_type: '10-Q' } },
      },
    ]);

    expect(manager.get('doc-1')).toEqual({
      doc_id: 'doc-1',
      chunk_id: 'chunk-1',
      source: 'a.md',
      label: 'ACME 2025 Q4 10Q',
    });

    expect(manager.get('doc-1', 'chunk-2')).toEqual({
      doc_id: 'doc-1',
      chunk_id: 'chunk-2',
      source: 'a.md',
      label: 'ACME 2025 Q4 10Q',
    });
  });

  it('chunk lookup takes precedence over doc lookup in get()', () => {
    const manager = new CitationManager();
    manager.updateFromChunks([
      {
        doc_id: 'doc-a',
        chunk_id: 'chunk-a',
        source: 'a.md',
        metadata: { doc: { ticker: 'AAA', filing_quarter: '2025 Q1', filing_type: '10-Q' } },
      },
      {
        doc_id: 'doc-b',
        chunk_id: 'chunk-b',
        source: 'b.md',
        metadata: { doc: { ticker: 'BBB', filing_quarter: '2025 Q2', filing_type: '10-Q' } },
      },
    ]);

    const target = manager.get('doc-a', 'chunk-b');
    expect(target?.doc_id).toBe('doc-b');
    expect(target?.chunk_id).toBe('chunk-b');
  });

  it('linkifyDocCitations leaves text unchanged when disabled', () => {
    const manager = new CitationManager();
    const html = 'claim [doc=doc-1 chunk=chunk-1]';

    expect(manager.linkifyDocCitations(html, { enable: false })).toBe(html);
  });

  it('linkifyDocCitations links doc+chunk citations with stable attributes', () => {
    const manager = new CitationManager();
    manager.updateFromChunks([
      {
        doc_id: 'doc-1',
        chunk_id: 'chunk-2',
        source: 'report.md',
        metadata: { doc: { ticker: 'ACME', filing_quarter: '2025 Q4', filing_type: '10-Q' } },
      },
    ]);

    const html = manager.linkifyDocCitations('claim [doc=doc-1 chunk=chunk-2 score=0.8]', { enable: true });

    expect(html).toContain('class="citationLink"');
    expect(html).toContain('data-doc-id="doc-1"');
    expect(html).toContain('data-chunk-id="chunk-2"');
    expect(html).toContain('ACME 2025 Q4 10Q');
  });

  it('linkifyDocCitations uses doc-level fallback chunk when chunk is not provided', () => {
    const manager = new CitationManager();
    manager.updateFromChunks([
      {
        doc_id: 'doc-2',
        chunk_id: 'chunk-9',
        source: 'report.md',
        metadata: { doc: { ticker: 'WIDG', filing_quarter: '2024 Q3', filing_type: '10-K' } },
      },
    ]);

    const html = manager.linkifyDocCitations('claim [doc=doc-2]', { enable: true });

    expect(html).toContain('data-doc-id="doc-2"');
    expect(html).toContain('data-chunk-id="chunk-9"');
    expect(html).toContain('WIDG 2024 Q3 10K');
  });

  it('linkifyDocCitations keeps unknown citations untouched', () => {
    const manager = new CitationManager();

    const html = manager.linkifyDocCitations('claim [doc=missing chunk=missing]', { enable: true });

    expect(html).toBe('claim [doc=missing chunk=missing]');
  });

  it('falls back to doc-based label when chunk metadata has no filing fields', () => {
    const manager = new CitationManager();
    manager.updateFromChunks([
      {
        doc_id: 'very-long-doc-id-12345',
        chunk_id: 'chunk-1',
        source: 'report.md',
        metadata: {},
      },
    ]);

    const html = manager.linkifyDocCitations('claim [doc=very-long-doc-id-12345 chunk=chunk-1]', { enable: true });

    expect(html).toContain('doc very-long-doc-...');
  });

  it('escapes HTML attributes in generated citation links', () => {
    const manager = new CitationManager();
    manager.updateFromChunks([
      {
        doc_id: 'doc"1',
        chunk_id: 'chunk"2',
        source: 'report.md',
        metadata: {
          doc: { ticker: 'ACME', filing_quarter: '2025 Q4', filing_type: '10-Q' },
        },
      },
    ]);

    const html = manager.linkifyDocCitations('claim [doc=doc"1 chunk=chunk"2]', { enable: true });

    expect(html).toContain('data-doc-id="doc&quot;1"');
    expect(html).toContain('data-chunk-id="chunk&quot;2"');
  });

  it('renders tool citation chip for [tool=...] markers', () => {
    const manager = new CitationManager();
    const html = manager.linkifyDocCitations(
      'snap [tool=edgar_get_financial_metrics ticker=SNDK status=ok]',
      { enable: true },
    );

    expect(html).toContain('class="toolCitationChip"');
    expect(html).toContain('edgar_get_financial_metrics · SNDK (ok)');
  });

  it('renders tool citation chip for tool-like [doc=...] markers', () => {
    const manager = new CitationManager();
    const html = manager.linkifyDocCitations(
      'snap [doc=yfinance_get_price_history ticker=SNDK status=ok]',
      { enable: true },
    );

    expect(html).toContain('class="toolCitationChip"');
    expect(html).toContain('yfinance_get_price_history · SNDK (ok)');
  });

  it('keeps non-tool [doc=...] markers untouched when not in citation map', () => {
    const manager = new CitationManager();
    const html = manager.linkifyDocCitations('claim [doc=random_unknown_doc_id ticker=SNDK status=ok]', {
      enable: true,
    });

    expect(html).toBe('claim [doc=random_unknown_doc_id ticker=SNDK status=ok]');
  });
});
