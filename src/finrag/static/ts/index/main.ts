import { safeText } from '../shared/html.js';
import { formatDuration } from '../shared/time.js';
import { renderHistoryList } from './history.js';
import { renderChunks } from './chunks.js';
import { CitationManager, extractDocMeta, formatCitationLabelFromChunk, formatDocMetaLine } from './citations.js';
import { els, DEFAULT_ANSWER_PANE_PCT, DEFAULT_SOURCES_PANE_WIDTH_PX, STEP_ORDER } from './dom.js';
import { GenerationModeManager } from './generation.js';
import { IngestedCompaniesPanel } from './ingested.js';
import { createLayoutController } from './layout.js';
import { renderMarkdown } from './markdown.js';
import { getTimingMs, ProgressUI, timingBits } from './progress.js';
import { readLocalHistory, readSettings, readUi, writeLocalHistory, writeSettings, writeUi } from './storage.js';
import { buildChunksBySource, isMarkdownSource, SourceViewer } from './source-viewer.js';

let historyItems: any[] = [];
let activeEntry: any = null;
let lastQueryResponse: any = null;
let lastRerankedChunks: any[] = [];
let lastRetrievedChunks: any[] = [];
let activeStream: { controller: AbortController; requestId: string | null } | null = null;

const generationModes = new GenerationModeManager();
const citationManager = new CitationManager();

const sourceViewer = new SourceViewer({
  els,
  renderMarkdown: (md: string): string => renderMarkdown(md),
  extractDocMeta,
  formatDocMetaLine,
});

const progressUi = new ProgressUI(
  {
    summary: els.progressSummaryPill,
    pipeline: els.progressPipeline,
    log: els.progressLog,
  },
  STEP_ORDER,
);

const layout = createLayoutController({
  els,
  readUi,
  writeUi,
  defaultSourcesPaneWidthPx: DEFAULT_SOURCES_PANE_WIDTH_PX,
  defaultAnswerPanePct: DEFAULT_ANSWER_PANE_PCT,
});

const ingestedPanel = new IngestedCompaniesPanel({
  status: els.ingestedStatus,
  list: els.ingestedList,
  countPill: els.ingestedCountPill,
  filter: els.ingestedFilter,
});

/** Render markdown answer text with optional citation linkification. */
function renderAnswerMarkdown(md: string, { citations = false }: { citations?: boolean } = {}): string {
  return renderMarkdown(md, {
    citations,
    linkifyDocCitations: (html, opts) => citationManager.linkifyDocCitations(html, opts),
  });
}

/** Read current generation controls into API request settings payload. */
function currentSettings(): any {
  const toInt = (v: unknown, fallback: number): number => {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
  };

  const mode = String(els.genMode?.value || '').trim().toLowerCase() || generationModes.getDefaultMode() || 'normal';

  return {
    mode,
    top_k_retrieve: toInt(els.topKRetrieve.value, 30),
    top_k_rerank: toInt(els.topKRerank.value, 8),
    draft_max_tokens: toInt(els.draftMaxTokens.value, 65536),
    final_max_tokens: toInt(els.finalMaxTokens.value, 32768),
  };
}

/** Apply persisted/request settings back into generation controls. */
function applySettings(settings: any): void {
  if (!settings) return;

  const mode = String(settings.mode || settings.generation_mode || '').trim().toLowerCase() || generationModes.getDefaultMode() || 'normal';
  if (els.genMode) {
    const selected = generationModes.hasMode(mode) ? mode : generationModes.getDefaultMode();
    els.genMode.value = selected;
    generationModes.updateModeHelp(selected, els.genModeHelp);
  }

  if (settings.top_k_retrieve) els.topKRetrieve.value = settings.top_k_retrieve;
  if (settings.top_k_rerank) els.topKRerank.value = settings.top_k_rerank;
  if (settings.draft_max_tokens) els.draftMaxTokens.value = settings.draft_max_tokens;
  if (settings.final_max_tokens) els.finalMaxTokens.value = settings.final_max_tokens;
}

/** Check backend health endpoint and update status pill styling/text. */
async function checkHealth(): Promise<void> {
  try {
    const res = await fetch('/health');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    els.healthPill.textContent = 'healthy';
    els.healthPill.style.borderColor = 'rgba(34,197,94,0.45)';
    els.healthPill.style.color = 'rgba(167,243,208,0.95)';
  } catch {
    els.healthPill.textContent = 'health check failed';
    els.healthPill.style.borderColor = 'rgba(239,68,68,0.45)';
    els.healthPill.style.color = 'rgba(254,202,202,0.95)';
  }
}

/** Render history sidebar from current in-memory history cache. */
function renderHistory(): void {
  renderHistoryList({
    items: historyItems,
    filterValue: String(els.historyFilter?.value || ''),
    activeEntryId: activeEntry?.id || null,
    historyCountEl: els.historyCount,
    historyListEl: els.historyList,
    steps: STEP_ORDER,
    onSelect: (entry) => {
      activeEntry = entry;
      els.activeEntryPill.textContent = entry.id ? `selected: ${entry.id.slice(0, 8)}` : 'selected';
      renderHistory();
      showEntry(entry);
    },
  });
}

/** Render chunk cards in either reranked or retrieved chunk container. */
function renderChunkList(
  chunks: any[],
  opts: {
    container?: HTMLElement;
    countPill?: HTMLElement | null;
    emptyText?: string;
  } = {},
): void {
  renderChunks(chunks, {
    container: opts.container || els.chunks,
    countPill: opts.countPill || els.chunkCountPill,
    emptyText: opts.emptyText,
    extractDocMeta,
    formatDocMetaLine,
    isMarkdownSource,
    onViewInApp: (source, chunkId) => {
      void sourceViewer.render(source, chunkId);
    },
    sourceViewerDetails: els.sourceViewerDetails,
    sourceSelect: els.sourceSelect,
  });
}

/** Display a selected history entry in the main answer/debug panes. */
function showEntry(entry: any): void {
  if (!entry) return;

  const res = entry.response || {};
  els.answerBlock.style.display = 'block';
  els.requestIdPill.textContent = entry.id ? 'hist ' + String(entry.id).slice(0, 8) : 'history';

  progressUi.reset();
  progressUi.applyTimingMs(entry?.timing_ms || {});
  const bits = timingBits(entry?.timing_ms || {}, STEP_ORDER);
  if (bits.length) progressUi.append(`timings: ${bits.join(' · ')}`);

  els.draftStatePill.textContent = 'done';

  citationManager.reset();
  const chunks = res.top_chunks || [];
  citationManager.updateFromChunks(chunks);

  els.draftAnswer.innerHTML = renderAnswerMarkdown(String(res.draft_answer ?? ''), { citations: true });
  els.finalAnswer.innerHTML = renderAnswerMarkdown(String(res.final_answer ?? ''), { citations: true });

  renderChunkList(chunks);

  sourceViewer.setChunksBySource(buildChunksBySource(chunks));
  void sourceViewer.populateSourceSelect();

  lastQueryResponse = res;
  els.copyAnswerBtn.disabled = !String(res.final_answer ?? '').trim();
  els.copyDebugBtn.disabled = false;
}

/** Reset interactive query view to idle/new-chat state. */
function resetChatView({ clearQuestion = true, resetAnswerSplit = false }: { clearQuestion?: boolean; resetAnswerSplit?: boolean } = {}): void {
  activeEntry = null;
  lastQueryResponse = null;
  citationManager.reset();
  lastRerankedChunks = [];
  lastRetrievedChunks = [];

  sourceViewer.clearChunks();

  if (clearQuestion) els.question.value = '';
  els.queryStatus.textContent = '';
  els.activeEntryPill.textContent = 'no selection';
  renderHistory();

  if (resetAnswerSplit) {
    const applied = layout.setAnswerPanePct(DEFAULT_ANSWER_PANE_PCT);
    if (typeof applied === 'number') writeUi({ answerPanePct: applied });
  }

  els.answerBlock.style.display = 'block';
  els.requestIdPill.textContent = 'idle';
  progressUi.reset();
  els.draftStatePill.textContent = 'waiting';
  els.draftAnswer.innerHTML = '';
  els.finalAnswer.innerHTML = '<div class="muted">Ask a question below to see the answer here.</div>';
  els.copyAnswerBtn.disabled = true;
  els.copyDebugBtn.disabled = true;

  els.retrievedCountPill.textContent = '0 chunks';
  els.retrievedChunks.innerHTML = '';
  if (els.retrievedDetails) els.retrievedDetails.open = false;
  if (els.draftDetails) els.draftDetails.open = false;

  renderChunkList([], {
    container: els.chunks,
    countPill: els.chunkCountPill,
    emptyText: 'No chunks yet.',
  });
  void sourceViewer.populateSourceSelect();
}

/** Pull latest history rows from server and refresh local cache + UI. */
async function loadHistoryFromServer(): Promise<any[]> {
  const res = await fetch('/history?limit=200');
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  const items = Array.isArray(data.items) ? data.items : [];
  historyItems = items;
  if (data.path && els.historyPath) els.historyPath.textContent = data.path;
  writeLocalHistory(items);
  renderHistory();
  return items;
}

/** Load history with local fast-path and server refresh fallback. */
async function loadHistory(): Promise<void> {
  historyItems = readLocalHistory();
  renderHistory();
  try {
    await loadHistoryFromServer();
  } catch (e) {
    console.warn('Failed to load /history; using local cache.', e);
  }
}

/** Delete server-side history file and clear local history state. */
async function clearHistory(): Promise<void> {
  if (!confirm('Delete server history? This removes the JSONL file.')) return;
  els.clearHistoryBtn.disabled = true;
  try {
    const res = await fetch('/history', { method: 'DELETE' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    historyItems = [];
    writeLocalHistory([]);
    renderHistory();
    resetChatView({ clearQuestion: false });
  } catch (e) {
    alert('Failed to clear history: ' + e);
  } finally {
    els.clearHistoryBtn.disabled = false;
  }
}

/** Download arbitrary object as pretty-printed JSON file in browser. */
function downloadJson(filename: string, obj: unknown): void {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Export history as JSON file by calling `/history` endpoint. */
async function exportHistory(): Promise<void> {
  try {
    const res = await fetch('/history?limit=2000');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const items = Array.isArray(data.items) ? data.items : [];
    downloadJson('finrag_history.json', items);
  } catch (e) {
    alert('Failed to export history: ' + e);
  }
}

/** Abort active stream and send best-effort backend cancel signal. */
async function stopActiveQuery(): Promise<void> {
  const stream = activeStream;
  if (!stream) return;

  try {
    stream.controller.abort();
  } catch {
    // no-op
  }

  const requestId = stream.requestId;
  if (requestId) {
    fetch('/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
    }).catch(() => {});
  }

  activeStream = null;
}

/** Execute the full streaming query flow and update UI incrementally. */
async function doQuery(question: string): Promise<void> {
  const settings = currentSettings();
  writeSettings(settings);

  els.queryBtn.disabled = true;
  els.stopBtn.disabled = false;
  els.queryStatus.textContent = 'Starting…';
  els.copyAnswerBtn.disabled = true;
  els.copyDebugBtn.disabled = true;

  els.answerBlock.style.display = 'block';
  els.requestIdPill.textContent = '…';
  progressUi.reset();
  progressUi.setSummary('running');
  els.draftStatePill.textContent = 'waiting';
  els.draftAnswer.innerHTML = '';
  els.finalAnswer.innerHTML = '';
  els.retrievedCountPill.textContent = '0 chunks';
  els.retrievedChunks.innerHTML = '';

  renderChunkList([], { container: els.chunks, countPill: els.chunkCountPill });

  sourceViewer.clearChunks();
  void sourceViewer.populateSourceSelect();

  citationManager.reset();
  lastRerankedChunks = [];
  lastRetrievedChunks = [];

  let draftText = '';
  let finalText = '';
  let draftRenderTimer: number | null = null;
  let finalRenderTimer: number | null = null;
  let streamState: { controller: AbortController; requestId: string | null } | null = null;

  const queryT0 = performance.now();
  const stepStarts = new Map<string, number>();
  const stepDurations = new Map<string, number>();

  const startStep = (step: string): void => {
    const s = String(step || '').trim();
    if (!s) return;
    if (!stepStarts.has(s)) stepStarts.set(s, performance.now());
    progressUi.setStep(s, 'running', null);
  };

  const finishStep = (step: string, serverMs: unknown): number | null => {
    const s = String(step || '').trim();
    if (!s) return null;
    let ms: number | null = null;
    if (typeof serverMs === 'number' && Number.isFinite(serverMs) && serverMs >= 0) {
      ms = serverMs;
    } else {
      const t0 = stepStarts.get(s);
      if (typeof t0 === 'number') ms = performance.now() - t0;
    }
    if (ms !== null) {
      stepDurations.set(s, ms);
      progressUi.setStep(s, 'done', ms);
    }
    return ms;
  };

  const stepSummary = (): string => {
    const parts: string[] = [];
    for (const key of STEP_ORDER) {
      if (!stepDurations.has(key)) continue;
      parts.push(`${key} ${formatDuration(stepDurations.get(key))}`);
    }
    return parts.length ? parts.join(' · ') : '';
  };

  try {
    await stopActiveQuery();

    const controller = new AbortController();
    streamState = { controller, requestId: null };
    activeStream = streamState;

    const res = await fetch('/query_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, ...settings }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);

    const reader = res.body?.getReader();
    if (!reader) throw new Error('Missing response body');

    const decoder = new TextDecoder();
    let buf = '';

    const scheduleDraftRender = (): void => {
      if (draftRenderTimer !== null) return;
      draftRenderTimer = window.setTimeout(() => {
        els.draftAnswer.innerHTML = renderAnswerMarkdown(draftText, { citations: true });
        draftRenderTimer = null;
      }, 120);
    };

    const scheduleFinalRender = (): void => {
      if (finalRenderTimer !== null) return;
      finalRenderTimer = window.setTimeout(() => {
        els.finalAnswer.innerHTML = renderAnswerMarkdown(finalText, { citations: true });
        finalRenderTimer = null;
      }, 120);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let idx = -1;
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        if (!line.trim()) continue;

        let evt: any = null;
        try {
          evt = JSON.parse(line);
        } catch {
          continue;
        }

        const type = String(evt?.type || '');

        if (type === 'start') {
          streamState.requestId = String(evt?.request_id || '');
          els.requestIdPill.textContent = streamState.requestId ? 'req ' + streamState.requestId.slice(0, 8) : 'req';
          progressUi.setSummary('running');
          progressUi.append('Started ' + els.requestIdPill.textContent);
          continue;
        }

        if (type === 'status') {
          const msg = String(evt?.message || '');
          const step = String(evt?.step || '');
          if (step) startStep(step);
          els.queryStatus.textContent = msg || (step ? 'Step: ' + step : '');
          progressUi.append(step ? step + ': ' + msg : msg);
          if (step === 'draft') {
            els.draftStatePill.textContent = 'streaming';
            els.draftDetails.open = true;
          }
          continue;
        }

        if (type === 'retrieved') {
          const chunks = Array.isArray(evt?.chunks) ? evt.chunks : [];
          lastRetrievedChunks = chunks;
          renderChunkList(chunks, {
            container: els.retrievedChunks,
            countPill: els.retrievedCountPill,
          });
          els.retrievedDetails.open = true;
          const ms = finishStep('retrieve', evt?.step_ms ?? evt?.retrieve_ms);
          const dur = formatDuration(ms, { empty: '' });
          const count = String(evt?.count ?? chunks.length);
          progressUi.append(dur ? `retrieve: ${dur} · ${count} chunks` : `Retrieved ${count} chunks`);
          continue;
        }

        if (type === 'reranked') {
          const chunks = Array.isArray(evt?.chunks) ? evt.chunks : [];
          lastRerankedChunks = chunks;
          citationManager.updateFromChunks(chunks);
          renderChunkList(chunks, {
            container: els.chunks,
            countPill: els.chunkCountPill,
          });

          sourceViewer.setChunksBySource(buildChunksBySource(chunks));
          await sourceViewer.populateSourceSelect();

          scheduleDraftRender();
          scheduleFinalRender();

          const ms = finishStep('rerank', evt?.step_ms ?? evt?.rerank_ms);
          const dur = formatDuration(ms, { empty: '' });
          const count = String(evt?.count ?? chunks.length);
          progressUi.append(dur ? `rerank: ${dur} · ${count} chunks` : `Reranked ${count} chunks`);
          continue;
        }

        if (type === 'draft_delta') {
          const delta = String(evt?.delta || '');
          if (delta) {
            draftText += delta;
            els.draftDetails.open = true;
            scheduleDraftRender();
          }
          continue;
        }

        if (type === 'draft_done') {
          els.draftStatePill.textContent = 'done';
          const ms = finishStep('draft', evt?.step_ms ?? evt?.draft_ms);
          const dur = formatDuration(ms, { empty: '' });
          progressUi.append(dur ? `draft: ${dur} · ready` : 'Draft ready');
          continue;
        }

        if (type === 'final_delta') {
          const delta = String(evt?.delta || '');
          if (delta) {
            finalText += delta;
            scheduleFinalRender();
          }
          continue;
        }

        if (type === 'cancelled') {
          els.queryStatus.textContent = 'Cancelled.';
          const elapsed = performance.now() - queryT0;
          progressUi.setSummary(`cancelled ${formatDuration(elapsed)}`, 'bad');
          progressUi.append(`Cancelled · ${formatDuration(elapsed)}`);
          break;
        }

        if (type === 'error') {
          const err = String(evt?.error || 'Unknown error');
          els.queryStatus.textContent = 'Error: ' + err;
          progressUi.setSummary('error', 'bad');
          for (const step of STEP_ORDER) {
            if (!stepDurations.has(step) && stepStarts.has(step)) progressUi.setStep(step, 'error', null);
          }
          progressUi.append('Error: ' + err);
          break;
        }

        if (type === 'done') {
          const data = evt?.response || {};
          lastQueryResponse = data;
          els.queryStatus.textContent = '';

          els.draftStatePill.textContent = 'done';
          draftText = String(data.draft_answer ?? draftText);
          finalText = String(data.final_answer ?? finalText);
          citationManager.updateFromChunks(data.top_chunks || []);

          els.draftAnswer.innerHTML = renderAnswerMarkdown(draftText, { citations: true });
          els.finalAnswer.innerHTML = renderAnswerMarkdown(finalText, { citations: true });

          const chunks = data.top_chunks || [];
          renderChunkList(chunks, {
            container: els.chunks,
            countPill: els.chunkCountPill,
          });

          sourceViewer.setChunksBySource(buildChunksBySource(chunks));
          await sourceViewer.populateSourceSelect();

          els.copyAnswerBtn.disabled = !String(finalText || '').trim();
          els.copyDebugBtn.disabled = false;

          await loadHistoryFromServer();

          const timing = evt?.timing_ms && typeof evt.timing_ms === 'object' ? evt.timing_ms : {};
          finishStep('final', evt?.final_ms ?? timing?.final_ms);
          if (Object.keys(timing).length) {
            progressUi.applyTimingMs(timing);
          } else {
            for (const step of STEP_ORDER) {
              if (!stepDurations.has(step)) progressUi.setStep(step, 'skipped', null);
            }
          }

          const totalMs = Number(evt?.elapsed_ms);
          const totalFromTiming = getTimingMs(timing, 'total_ms');
          const total =
            totalFromTiming !== null
              ? totalFromTiming
              : Number.isFinite(totalMs)
                ? totalMs
                : performance.now() - queryT0;

          progressUi.setSummary(`total ${formatDuration(total)}`, 'ok');
          const summary = stepSummary();
          progressUi.append(`Done in ${formatDuration(total)}${summary ? ' · ' + summary : ''}`);
          break;
        }
      }
    }
  } catch (e: any) {
    if (String(e?.name || '') === 'AbortError') {
      els.queryStatus.textContent = 'Cancelled.';
      progressUi.setSummary('cancelled', 'bad');
      progressUi.append('Cancelled');
    } else {
      console.error(e);
      els.queryStatus.textContent = 'Error: ' + e;
      progressUi.setSummary('error', 'bad');
      progressUi.append('Error: ' + e);
    }
  } finally {
    els.queryBtn.disabled = false;
    els.stopBtn.disabled = true;
    if (!streamState?.controller?.signal?.aborted) {
      els.requestIdPill.textContent = streamState?.requestId ? 'req ' + streamState.requestId.slice(0, 8) : 'idle';
    }
    if (activeStream === streamState) activeStream = null;
  }
}

/** Resolve citation target metadata by doc id across active chunk sets. */
function findChunkTargetForDocId(docId: string): any | null {
  const d = String(docId || '').trim();
  if (!d) return null;

  const direct = citationManager.get(d);
  if (direct) return direct;

  const fromReranked = (Array.isArray(lastRerankedChunks) ? lastRerankedChunks : []).find(
    (c) => String(c?.doc_id || '').trim() === d,
  );
  if (fromReranked) {
    const label = formatCitationLabelFromChunk(fromReranked);
    if (!label) return null;
    return {
      doc_id: d,
      chunk_id: String(fromReranked.chunk_id || ''),
      source: String(fromReranked.source || ''),
      label,
    };
  }

  const fromRetrieved = (Array.isArray(lastRetrievedChunks) ? lastRetrievedChunks : []).find(
    (c) => String(c?.doc_id || '').trim() === d,
  );
  if (fromRetrieved) {
    const label = formatCitationLabelFromChunk(fromRetrieved);
    if (!label) return null;
    return {
      doc_id: d,
      chunk_id: String(fromRetrieved.chunk_id || ''),
      source: String(fromRetrieved.source || ''),
      label,
    };
  }

  const fromDone = (Array.isArray(lastQueryResponse?.top_chunks) ? lastQueryResponse.top_chunks : []).find(
    (c: any) => String(c?.doc_id || '').trim() === d,
  );
  if (fromDone) {
    const label = formatCitationLabelFromChunk(fromDone);
    if (!label) return null;
    return {
      doc_id: d,
      chunk_id: String(fromDone.chunk_id || ''),
      source: String(fromDone.source || ''),
      label,
    };
  }

  return null;
}

/** Open source viewer at citation target for the given document id. */
async function jumpToCitation(docId: string): Promise<void> {
  const target = findChunkTargetForDocId(docId);
  if (!target) return;
  const src = String(target.source || '').trim();
  const chunkId = String(target.chunk_id || '').trim();
  if (!src || !chunkId) return;

  els.sourceViewerDetails.open = true;
  els.sourceSelect.value = src;
  await sourceViewer.render(src, chunkId);
}

/** Handle clicks on citation links embedded in rendered answers. */
function onCitationClick(e: Event): void {
  const target = e.target as Element | null;
  const link = target?.closest?.('a.citationLink') as HTMLAnchorElement | null;
  if (!link) return;
  e.preventDefault();
  const docId = String(link.getAttribute('data-doc-id') || '').trim();
  void jumpToCitation(docId);
}

els.queryForm.addEventListener('submit', async (e: Event) => {
  e.preventDefault();
  const q = String(els.question.value || '').trim();
  if (!q) {
    els.queryStatus.textContent = 'Please enter a question.';
    return;
  }
  await doQuery(q);
});

els.stopBtn.addEventListener('click', async () => {
  await stopActiveQuery();
});

els.historyFilter.addEventListener('input', () => renderHistory());
els.newChatBtn?.addEventListener('click', async () => {
  await stopActiveQuery();
  resetChatView({ clearQuestion: true, resetAnswerSplit: true });
});
els.reloadHistoryBtn.addEventListener('click', () => {
  void loadHistory();
});
els.clearHistoryBtn.addEventListener('click', () => {
  void clearHistory();
});
els.exportHistoryBtn.addEventListener('click', () => {
  void exportHistory();
});

els.copyAnswerBtn.addEventListener('click', async () => {
  const text = String(lastQueryResponse?.final_answer ?? '');
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    alert('Clipboard write failed');
  }
});

els.copyDebugBtn.addEventListener('click', async () => {
  const payload = {
    question: String(els.question.value || ''),
    settings: currentSettings(),
    response: lastQueryResponse,
    selected_history_entry: activeEntry,
  };
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
  } catch {
    alert('Clipboard write failed');
  }
});

els.draftAnswer?.addEventListener('click', onCitationClick);
els.finalAnswer?.addEventListener('click', onCitationClick);

els.sourceSelect.addEventListener('change', async () => {
  await sourceViewer.render(els.sourceSelect.value, null);
});
els.sourceReloadBtn.addEventListener('click', async () => {
  await sourceViewer.reloadCurrent();
});
els.sourceToggleModeBtn.addEventListener('click', async () => {
  sourceViewer.toggleMode();
  await sourceViewer.render(els.sourceSelect.value, null);
});

els.genMode?.addEventListener('change', () => {
  const mode = String(els.genMode.value || '').trim().toLowerCase();
  generationModes.applyModePreset(mode, {
    topKRetrieve: els.topKRetrieve,
    topKRerank: els.topKRerank,
    draftMaxTokens: els.draftMaxTokens,
    finalMaxTokens: els.finalMaxTokens,
  });
  generationModes.updateModeHelp(mode, els.genModeHelp);
  writeSettings(currentSettings());
});

els.ingestedFilter?.addEventListener('input', () => {
  ingestedPanel.render();
});

/** Bootstrap controls, persisted state, and initial background loads. */
(async function init() {
  await generationModes.loadFromServer();
  generationModes.populateSelect(els.genMode);

  const saved = readSettings() || {};
  const savedMode = String(saved.mode || saved.generation_mode || '').trim().toLowerCase();
  const mode = generationModes.hasMode(savedMode) ? savedMode : generationModes.getDefaultMode();
  if (els.genMode) els.genMode.value = mode;

  generationModes.applyModePreset(
    mode,
    {
      topKRetrieve: els.topKRetrieve,
      topKRerank: els.topKRerank,
      draftMaxTokens: els.draftMaxTokens,
      finalMaxTokens: els.finalMaxTokens,
    },
    { overwriteAdvanced: true },
  );
  generationModes.updateModeHelp(mode, els.genModeHelp);
  applySettings(saved);

  layout.applyUi(readUi());
  layout.setupSourcesSplitter();
  layout.setupAnswerSplitter();

  void sourceViewer.populateSourceSelect();
  void checkHealth();
  void ingestedPanel.load();
  void loadHistory();
})();
