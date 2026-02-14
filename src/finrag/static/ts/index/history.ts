import { safeText } from '../shared/html.js';
import { fmtDate, formatDuration } from '../shared/time.js';
import { getTimingMs, timingBits } from './progress.js';

/** Render history sidebar entries with filters, timing chips, and selection state. */
export function renderHistoryList(opts: {
  items: any[];
  filterValue: string;
  activeEntryId: string | null;
  historyCountEl: HTMLElement;
  historyListEl: HTMLElement;
  steps: string[];
  onSelect: (entry: any) => void;
}): void {
  const q = String(opts.filterValue || '').trim().toLowerCase();
  const filtered = q
    ? opts.items.filter((item) => String(item?.request?.question || '').toLowerCase().includes(q))
    : opts.items;

  opts.historyCountEl.textContent = String(filtered.length);
  opts.historyListEl.innerHTML = '';

  if (!filtered.length) {
    const div = document.createElement('div');
    div.className = 'panelBody muted';
    div.textContent = q ? 'No matches.' : 'No history yet. Ask a question to create entries.';
    opts.historyListEl.appendChild(div);
    return;
  }

  filtered.forEach((entry) => {
    const div = document.createElement('div');
    const active = opts.activeEntryId && entry?.id === opts.activeEntryId;
    div.className = 'historyItem' + (active ? ' active' : '');

    const question = entry?.request?.question || '(missing question)';
    const when = fmtDate(entry?.created_at);
    const chunks = entry?.response?.top_chunks?.length ?? entry?.response?.top_chunks_count ?? 0;
    const mode = String(entry?.request?.mode || '').trim().toLowerCase();
    const timing = entry && typeof entry.timing_ms === 'object' ? entry.timing_ms : {};
    const totalMs = getTimingMs(timing, 'total_ms');
    const bits = timingBits(timing, opts.steps);
    const summary = totalMs !== null ? `total ${formatDuration(totalMs)}` : '';

    div.innerHTML = `
      <div class="historyQ">${safeText(question)}</div>
      <div class="historyMeta">
        <span>${safeText(when)}</span>
        <span class="pill">${chunks} chunks</span>
        ${mode ? `<span class="pill">mode: ${safeText(mode)}</span>` : ''}
        ${summary ? `<span class="pill ok">${safeText(summary)}</span>` : ''}
      </div>
      ${bits.length ? `<div class="historyTiming">${safeText(bits.join(' · '))}</div>` : ''}
    `;

    div.addEventListener('click', () => {
      opts.onSelect(entry);
    });

    opts.historyListEl.appendChild(div);
  });
}
