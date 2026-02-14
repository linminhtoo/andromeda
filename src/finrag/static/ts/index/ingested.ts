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
          return ticker.toLowerCase().includes(q) || company.toLowerCase().includes(q);
        })
      : items;

    this.els.countPill.textContent = String(items.length);
    const prefix = this.statusBase ? this.statusBase + ' · ' : '';
    this.els.status.textContent = q ? `${prefix}Showing ${filtered.length} of ${items.length}` : this.statusBase;

    if (!filtered.length) {
      this.els.list.innerHTML = '<div class="muted">No matches.</div>';
      return;
    }

    this.els.list.innerHTML = filtered
      .map((it) => {
        const ticker = String(it?.ticker || '').trim();
        const company = this.cleanCompany(it?.company, ticker);
        return `<div class="code">${safeText(ticker)} — ${safeText(company)}</div>`;
      })
      .join('');
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
