import { safeText } from '../shared/html.js';

/** Resolve a source field to an absolute app href when possible. */
export function sourceHref(source: unknown): string | null {
  const s = String(source || '').trim();
  if (!s) return null;
  if (s.startsWith('http://') || s.startsWith('https://')) return s;
  return '/source?path=' + encodeURIComponent(s);
}

/** Render a list of retrieval chunks with metadata and source actions. */
export function renderChunks(
  chunks: any[],
  opts: {
    container: HTMLElement;
    countPill?: HTMLElement | null;
    emptyText?: string;
    extractDocMeta: (chunk: any) => any | null;
    formatDocMetaLine: (doc: any) => string;
    isMarkdownSource: (source: unknown) => boolean;
    onViewInApp?: (source: string, chunkId: string) => void;
    sourceViewerDetails?: HTMLElement | null;
    sourceSelect?: HTMLSelectElement | null;
  },
): void {
  const list = Array.isArray(chunks) ? chunks : [];
  if (opts.countPill) opts.countPill.textContent = `${list.length} chunks`;
  opts.container.innerHTML = '';
  if (!list.length) {
    opts.container.innerHTML = `<div class="muted">${safeText(String(opts.emptyText || 'No chunks returned.'))}</div>`;
    return;
  }

  list.forEach((chunk, idx) => {
    const headings = Array.isArray(chunk.headings) && chunk.headings.length ? chunk.headings.join(' › ') : '';
    const href = sourceHref(chunk.source);
    const score = typeof chunk.score === 'number' ? chunk.score.toFixed(3) : String(chunk.score ?? '');
    const meta = chunk && typeof chunk.metadata === 'object' ? chunk.metadata : null;
    const doc = opts.extractDocMeta(chunk);
    const docLine = opts.formatDocMetaLine(doc);
    const summary = meta && typeof meta.summary === 'string' ? meta.summary.trim() : '';
    const chunkText = String(chunk.text ?? '');
    const src = String(chunk.source || '').trim();
    const canViewInApp = opts.isMarkdownSource(src);

    const details = document.createElement('details');
    details.style.marginBottom = '0.6rem';
    details.innerHTML = `
      <summary>
        <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap: wrap;">
          <span class="pill">#${idx + 1}</span>
          <span class="pill">score=${safeText(score)}</span>
          <span class="pill">doc=${safeText(chunk.doc_id ?? '')}</span>
          <span class="pill">chunk=${safeText(chunk.chunk_id ?? '')}</span>
          ${doc?.company ? `<span class="pill">co=${safeText(doc.company)}</span>` : ''}
          ${doc?.ticker ? `<span class="pill">ticker=${safeText(doc.ticker)}</span>` : ''}
          ${doc?.filing_type ? `<span class="pill">${safeText(doc.filing_type)}</span>` : ''}
          ${doc?.filing_date ? `<span class="pill">filed=${safeText(doc.filing_date)}</span>` : ''}
        </div>
        <div class="muted" style="font-size: 0.86rem;">toggle</div>
      </summary>
      <div class="chunkBody">
        ${docLine ? `<div class="help" style="margin-bottom:0.35rem;">${docLine}</div>` : ''}
        ${headings ? `<div style="margin-bottom:0.35rem;"><strong>${safeText(headings)}</strong></div>` : ''}
        ${summary ? `<div class="muted" style="margin-bottom:0.35rem;">${safeText(summary)}</div>` : ''}
        <div class="row" style="margin-bottom: 0.6rem;">
          ${href ? `<a href="${href}" target="_blank" rel="noopener">Open source</a>` : '<span class="muted">No source link</span>'}
          <button class="btn" type="button" data-action="view-in-app" ${canViewInApp ? '' : 'disabled'}>View in app</button>
          <span class="pill">${canViewInApp ? 'markdown' : 'non-markdown'}</span>
        </div>
        ${chunkText ? `<div class="chunkText">${safeText(chunkText)}</div>` : '<div class="muted">Chunk text not included yet.</div>'}
      </div>
    `;

    details.addEventListener('toggle', () => {
      if (!details.open || !canViewInApp || !opts.onViewInApp) return;
      if (opts.sourceViewerDetails) (opts.sourceViewerDetails as HTMLDetailsElement).open = true;
      if (opts.sourceSelect) opts.sourceSelect.value = src;
      opts.onViewInApp(src, String(chunk.chunk_id || ''));
    });

    const btn = details.querySelector('button[data-action="view-in-app"]');
    if (btn) {
      btn.addEventListener('click', (e: Event) => {
        e.preventDefault();
        if (!opts.onViewInApp) return;
        if (opts.sourceViewerDetails) (opts.sourceViewerDetails as HTMLDetailsElement).open = true;
        if (opts.sourceSelect) opts.sourceSelect.value = src;
        opts.onViewInApp(src, String(chunk.chunk_id || ''));
      });
    }

    opts.container.appendChild(details);
  });
}
