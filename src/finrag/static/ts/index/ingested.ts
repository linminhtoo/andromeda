import { safeText } from '../shared/html.js';

/** Encapsulate load/render behavior for the ingested companies side panel. */
export class IngestedCompaniesPanel {
  private companies: any[] = [];
  private statusBase = '';

  constructor(private readonly els: { status: HTMLElement; list: HTMLElement; countPill: HTMLElement; filter: HTMLInputElement }) {}

  /** Normalize noisy company labels from doc index into stable display text. */
  private cleanCompany(company: unknown, ticker: unknown): string {
    const c = String(company || '').trim();
    const t = String(ticker || '').trim();
    const cl = c.toLowerCase();
    if (!c) return t || '';
    if (cl === 'table of contents' || cl.startsWith('table of contents')) return t || '';
    if (cl === 'index' || cl.startsWith('index ')) return t || '';
    if (cl.includes('table of contents')) return t || '';
    return c;
  }

  /** Render current ingested companies view with active search filter. */
  render(): void {
    const q = String(this.els.filter?.value || '').trim().toLowerCase();
    const items = Array.isArray(this.companies) ? this.companies : [];
    const filtered = q
      ? items.filter((it) => {
          const ticker = String(it?.ticker || '');
          const company = this.cleanCompany(it?.company, ticker);
          if (ticker.toLowerCase().includes(q) || company.toLowerCase().includes(q)) return true;
          const docs = Array.isArray(it?.documents) ? it.documents : [];
          return docs.some((doc) => {
            const relpath = String(doc?.relpath || '').toLowerCase();
            const formType = String(doc?.form_type || '').toLowerCase();
            const filingDate = String(doc?.filing_date || '').toLowerCase();
            return relpath.includes(q) || formType.includes(q) || filingDate.includes(q);
          });
        })
      : items;

    this.els.countPill.textContent = String(items.length);
    const prefix = this.statusBase ? this.statusBase + ' · ' : '';
    this.els.status.textContent = q ? `${prefix}Showing ${filtered.length} of ${items.length}` : this.statusBase;

    if (!filtered.length) {
      this.els.list.innerHTML = '<div class="muted">No matches.</div>';
      return;
    }

    this.els.list.innerHTML = `<div class="ingestedCards">${filtered.map((it, idx) => this.renderCompanyCard(it, idx)).join('')}</div>`;
    this.wireCardToggles();
  }

  /** Render one ticker-level expandable card with document details and links. */
  private renderCompanyCard(item: any, idx: number): string {
    const ticker = String(item?.ticker || '').trim();
    const company = this.cleanCompany(item?.company, ticker);
    const docs = Array.isArray(item?.documents) ? item.documents : [];
    const documentCount = Number(item?.document_count);
    const totalChunks = Number(item?.total_chunks);
    const latestFilingDate = String(item?.latest_filing_date || '').trim();
    const countText = Number.isFinite(documentCount) ? `${documentCount}` : `${docs.length}`;
    const chunkText = Number.isFinite(totalChunks) ? `${totalChunks}` : '—';
    const open = idx < 2;

    const rows = docs
      .map((doc: any) => {
        const relpath = String(doc?.relpath || '').trim();
        const formType = String(doc?.form_type || '').trim();
        const filingDate = String(doc?.filing_date || '').trim();
        const numChunks = doc?.num_chunks;
        const docId = String(doc?.doc_id || '').trim();
        const source = String(doc?.source || '').trim();
        const chunksPath = String(doc?.chunks_path || '').trim();
        const sourceLink = source ? `/source?path=${encodeURIComponent(source)}` : '';
        const chunksLink = chunksPath ? `/source?path=${encodeURIComponent(chunksPath)}` : '';
        return `
          <tr>
            <td class="code">${safeText(formType || '—')}</td>
            <td class="code">${safeText(filingDate || '—')}</td>
            <td class="code">${safeText(relpath || '—')}</td>
            <td class="code">${safeText(Number.isFinite(Number(numChunks)) ? String(numChunks) : '—')}</td>
            <td class="code">${safeText(docId || '—')}</td>
            <td>
              ${sourceLink ? `<a href="${safeText(sourceLink)}" target="_blank" rel="noopener">source</a>` : '<span class="muted">—</span>'}
              ${chunksLink ? ` · <a href="${safeText(chunksLink)}" target="_blank" rel="noopener">chunks</a>` : ''}
            </td>
          </tr>
        `;
      })
      .join('');

    return `
      <div class="ingestedCard${open ? ' open' : ''}">
        <button class="ingestedCardHead ingestedToggle" type="button" aria-expanded="${open ? 'true' : 'false'}">
          <div class="ingestedCardTitle">
            <span class="ingestedTicker">${safeText(ticker || '—')}</span>
            <span class="ingestedCompany">${safeText(company || '—')}</span>
          </div>
          <div style="display:flex; gap:0.4rem; align-items:center; flex-wrap:wrap;">
            <span class="pill">${safeText(countText)} docs</span>
            <span class="pill">${safeText(chunkText)} chunks</span>
            ${latestFilingDate ? `<span class="pill">${safeText(latestFilingDate)}</span>` : ''}
          </div>
        </button>
        <div class="chunkBody ingestedCardBody">
          <table class="ingestedDocTable">
            <thead>
              <tr>
                <th>Form</th>
                <th>Date</th>
                <th>Document</th>
                <th>Chunks</th>
                <th>Doc ID</th>
                <th>Open</th>
              </tr>
            </thead>
            <tbody>
              ${rows || '<tr><td colspan="6" class="muted">No documents found.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  /** Attach toggle behavior for document cards rendered as custom expandable panels. */
  private wireCardToggles(): void {
    const buttons = this.els.list.querySelectorAll('.ingestedToggle');
    buttons.forEach((button) => {
      button.addEventListener('click', () => {
        const card = button.closest('.ingestedCard');
        if (!card) return;
        const open = card.classList.toggle('open');
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });
  }

  /** Fetch ingested companies payload and refresh panel state. */
  async load(): Promise<void> {
    this.statusBase = 'Loading…';
    this.els.status.textContent = this.statusBase;
    this.els.countPill.textContent = '…';

    try {
      const res = await fetch('/ingested_companies');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      this.companies = Array.isArray(data?.items) ? data.items : [];
      this.statusBase = data?.path ? `From ${String(data.path)}` : data?.warning ? String(data.warning) : '';
      this.render();
    } catch {
      this.statusBase = 'Failed to load. Set FINRAG_DOC_INDEX_PATH and reload.';
      this.els.status.textContent = this.statusBase;
      this.els.list.innerHTML = '<div class="muted">Unavailable.</div>';
      this.els.countPill.textContent = '0';
    }
  }
}
