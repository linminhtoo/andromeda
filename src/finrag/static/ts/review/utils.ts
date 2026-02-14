import { formatDuration } from '../shared/time.js';
import { els, state } from './dom.js';

/** Set global review-page status line and semantic color state. */
export function setStatus(msg: string, kind: 'ok' | 'bad' | null = null): void {
  els.status.textContent = msg || '';
  els.status.classList.remove('statusOk', 'statusBad');
  if (kind === 'ok') els.status.classList.add('statusOk');
  if (kind === 'bad') els.status.classList.add('statusBad');
}

/** Set per-case save status line and semantic color state. */
export function setSaveStatus(msg: string, kind: 'ok' | 'bad' | null = null): void {
  els.saveStatus.textContent = msg || '';
  els.saveStatus.classList.remove('statusOk', 'statusBad');
  if (kind === 'ok') els.saveStatus.classList.add('statusOk');
  if (kind === 'bad') els.saveStatus.classList.add('statusBad');
}

/** Fetch JSON and raise rich errors that include API detail payloads. */
export async function fetchJSON(url: string, opts: RequestInit | undefined = undefined): Promise<any> {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = '';
    try {
      const j = await res.json();
      detail = j && j.detail ? String(j.detail) : JSON.stringify(j);
    } catch {
      detail = await res.text();
    }
    throw new Error(`HTTP ${res.status}: ${detail || res.statusText}`);
  }
  return await res.json();
}

/** Persist selected run/query into current URL query parameters. */
export function updateURL(runDir: string | null, queryId: string | null): void {
  const u = new URL(window.location.href);
  if (runDir) u.searchParams.set('run_dir', runDir);
  if (queryId) u.searchParams.set('query_id', queryId);
  history.replaceState(null, '', u.toString());
}

/** Normalize human/judge label values to accepted review enum strings. */
export function normalizeLabel(lbl: unknown): string {
  const v = String(lbl || '').trim();
  if (v === '0') return '0';
  if (v === '1') return '1';
  return '';
}

/** Sync judge-toggle button label with current in-memory state. */
export function syncJudgeToggleUI(): void {
  els.toggleJudgeBtn.textContent = state.showJudge ? 'Judge: on' : 'Judge: off';
}

/** Map human label value to display text + CSS class. */
export function labelPill(lbl: unknown): { text: string; cls: string } {
  const v = normalizeLabel(lbl);
  if (v === '0') return { text: 'pass', cls: 'pass' };
  if (v === '1') return { text: 'fail', cls: 'fail' };
  return { text: 'unlabeled', cls: '' };
}

/** Map judge prediction label to display text + CSS class. */
export function judgePill(pred: unknown): { text: string; cls: string } {
  const v = normalizeLabel(pred);
  if (v === '0') return { text: 'judge: pass', cls: 'pass' };
  if (v === '1') return { text: 'judge: fail', cls: 'fail' };
  return { text: 'judge: —', cls: '' };
}

/** Parse timing payload field into a non-negative millisecond number. */
export function timingMs(timing: any, key: string): number | null {
  const n = Number(timing && timing[key]);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** Format timing milliseconds with review-friendly empty fallback. */
export function formatMs(ms: unknown): string {
  return formatDuration(ms, { empty: '—' });
}
