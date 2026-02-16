import { safeText } from '../shared/html.js';
import { fmtDate, formatDuration } from '../shared/time.js';
import { getTimingMs, timingBits } from './progress.js';

export type ConversationHistoryGroup = {
  key: string;
  conversation_id: string | null;
  entries: any[];
  latest: any;
};

/** Group raw history rows into conversation buckets for sidebar rendering. */
export function groupHistoryByConversation(items: any[]): ConversationHistoryGroup[] {
  const list = Array.isArray(items) ? items : [];
  const groups: ConversationHistoryGroup[] = [];
  const byKey = new Map<string, ConversationHistoryGroup>();

  list.forEach((entry, idx) => {
    const rawConversationId = String(entry?.request?.conversation_id || entry?.response?.conversation_id || '').trim();
    const entryId = String(entry?.id || '').trim();
    const key = rawConversationId ? `conversation:${rawConversationId}` : `entry:${entryId || String(idx)}`;
    const conversationId = rawConversationId || null;

    let group = byKey.get(key);
    if (!group) {
      group = {
        key,
        conversation_id: conversationId,
        entries: [],
        latest: entry,
      };
      byKey.set(key, group);
      groups.push(group);
    }
    group.entries.push(entry);
    if (!group.latest) group.latest = entry;
  });

  return groups;
}

/** Render history sidebar entries with filters, timing chips, and selection state. */
export function renderHistoryList(opts: {
  groups: ConversationHistoryGroup[];
  filterValue: string;
  activeConversationKey: string | null;
  historyCountEl: HTMLElement;
  historyListEl: HTMLElement;
  steps: string[];
  onSelect: (group: ConversationHistoryGroup) => void;
}): void {
  const q = String(opts.filterValue || '').trim().toLowerCase();
  const filtered = q
    ? opts.groups.filter((group) =>
        group.entries.some((entry) => String(entry?.request?.question || '').toLowerCase().includes(q)),
      )
    : opts.groups;

  opts.historyCountEl.textContent = String(filtered.length);
  opts.historyListEl.innerHTML = '';

  if (!filtered.length) {
    const div = document.createElement('div');
    div.className = 'panelBody muted';
    div.textContent = q ? 'No matches.' : 'No history yet. Ask a question to create entries.';
    opts.historyListEl.appendChild(div);
    return;
  }

  filtered.forEach((group) => {
    const entry = group.latest;
    const div = document.createElement('div');
    const active = opts.activeConversationKey && group.key === opts.activeConversationKey;
    div.className = 'historyItem' + (active ? ' active' : '');

    const question = entry?.request?.question || '(missing question)';
    const when = fmtDate(entry?.created_at);
    const chunks = entry?.response?.top_chunks?.length ?? entry?.response?.top_chunks_count ?? 0;
    const turns = group.entries.length;
    const mode = String(entry?.request?.mode || '').trim().toLowerCase();
    const timing = entry && typeof entry.timing_ms === 'object' ? entry.timing_ms : {};
    const totalMs = getTimingMs(timing, 'total_ms');
    const bits = timingBits(timing, opts.steps);
    const summary = totalMs !== null ? `total ${formatDuration(totalMs)}` : '';

    div.innerHTML = `
      <div class="historyQ">${safeText(question)}</div>
      <div class="historyMeta">
        <span>${safeText(when)}</span>
        <span class="pill">${turns} turn${turns === 1 ? '' : 's'}</span>
        <span class="pill">${chunks} chunks</span>
        ${mode ? `<span class="pill">mode: ${safeText(mode)}</span>` : ''}
        ${summary ? `<span class="pill ok">${safeText(summary)}</span>` : ''}
      </div>
      ${bits.length ? `<div class="historyTiming">${safeText(bits.join(' · '))}</div>` : ''}
    `;

    div.addEventListener('click', () => {
      opts.onSelect(group);
    });

    opts.historyListEl.appendChild(div);
  });
}
