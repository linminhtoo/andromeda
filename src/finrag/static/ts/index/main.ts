import { escapeHtmlAttr, safeText, sanitizeHref } from '../shared/html.js';
import { fmtDate, formatDuration } from '../shared/time.js';
import { ConversationHistoryGroup, groupHistoryByConversation, renderHistoryList } from './history.js';
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
let historyGroups: ConversationHistoryGroup[] = [];
let activeEntry: any = null;
let lastQueryResponse: any = null;
let lastRerankedChunks: any[] = [];
let lastRetrievedChunks: any[] = [];
let lastToolResults: any[] = [];
let activeStream: { controller: AbortController; requestId: string | null } | null = null;
let activeConversationId: string | null = null;
let activeConversationKey: string | null = null;
let activeIngestJobId: string | null = null;
let activeIngestPollHandle: number | null = null;

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

/** Return true when current controls indicate two-stage draft+refine generation. */
function modeUsesDraft(modeOverride?: unknown, refineOverride?: unknown): boolean {
  if (refineOverride !== undefined && refineOverride !== null) return Boolean(refineOverride);
  if (els.enableRefine) return Boolean(els.enableRefine.checked);
  const mode = String(modeOverride || els.genMode?.value || '').trim().toLowerCase() || generationModes.getDefaultMode() || 'normal';
  return generationModes.modeUsesDraft(mode);
}

/** Show/hide draft panel to keep default layout compact for non-refine modes. */
function setDraftPanelVisibility(show: boolean): void {
  if (!els.draftDetails) return;
  els.draftDetails.hidden = !show;
  if (!show) {
    els.draftDetails.open = false;
    return;
  }
}

/** Collapse progress activity feed unless explicitly expanded. */
function collapseProgressLog(): void {
  if (!els.progressLogDetails) return;
  els.progressLogDetails.open = false;
}

/** Expand progress activity feed for debugging/error inspection. */
function expandProgressLog(): void {
  if (!els.progressLogDetails) return;
  els.progressLogDetails.open = true;
}

/** Render dedicated tool snapshot panel separate from markdown answer text. */
function renderToolResults(results: any[]): void {
  const list = Array.isArray(results) ? results : [];
  lastToolResults = list;
  if (els.toolResultsCountPill) els.toolResultsCountPill.textContent = String(list.length);
  if (els.toolResultsStatus) {
    els.toolResultsStatus.textContent = list.length ? `Showing ${list.length} tool result${list.length === 1 ? '' : 's'}.` : 'No tool results yet.';
  }
  if (!els.toolResults) return;
  if (!list.length) {
    els.toolResults.innerHTML = '';
    return;
  }

  const formatMetric = (value: unknown): string => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return Math.abs(value) >= 1000 ? value.toLocaleString() : String(value);
    }
    return String(value ?? '');
  };

  const renderPriceChartCard = (item: any): string => {
    const payload = item?.payload && typeof item.payload === 'object' ? item.payload : {};
    const series = Array.isArray(payload?.series) ? payload.series : [];
    const closeSeries = series
      .map((point: any) => ({
        t: String(point?.t || ''),
        close: Number(point?.close),
      }))
      .filter((point: any) => Number.isFinite(point.close));
    if (!closeSeries.length) return '';

    const width = 360;
    const height = 130;
    const padX = 14;
    const padY = 12;
    const values = closeSeries.map((point: any) => Number(point.close));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const innerW = width - padX * 2;
    const innerH = height - padY * 2;
    const points = closeSeries.map((point: any, idx: number) => {
      const x = padX + (innerW * idx) / Math.max(closeSeries.length - 1, 1);
      const y = padY + ((max - Number(point.close)) / span) * innerH;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    const first = Number(closeSeries[0]?.close);
    const last = Number(closeSeries[closeSeries.length - 1]?.close);
    const delta = last - first;
    const deltaPct = first === 0 ? 0 : (delta / first) * 100;
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(String(item?.ticker || 'n/a'))} price history</span>
          <span class="pill">${safeText(String(payload?.period || 'period'))}</span>
        </div>
        <div class="toolCardSummary">${safeText(String(item?.summary || ''))}</div>
        <svg class="toolChart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Price chart">
          <rect x="0" y="0" width="${width}" height="${height}" rx="10" ry="10" fill="#f5fafc"></rect>
          <polyline fill="none" stroke="#0f766e" stroke-width="2.2" points="${safeText(points.join(' '))}"></polyline>
        </svg>
        <div class="toolChartMeta">last ${formatMetric(last)} · min ${formatMetric(min)} · max ${formatMetric(max)} · ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} (${deltaPct.toFixed(2)}%)</div>
      </article>
    `;
  };

  const renderInfoCard = (item: any): string => {
    const payload = item?.payload && typeof item.payload === 'object' ? item.payload : {};
    const profile = payload?.profile && typeof payload.profile === 'object' ? payload.profile : {};
    const valuation = payload?.valuation && typeof payload.valuation === 'object' ? payload.valuation : {};
    const market = payload?.market && typeof payload.market === 'object' ? payload.market : {};
    const rows = [
      ['name', profile.longName],
      ['sector', profile.sector],
      ['industry', profile.industry],
      ['marketCap', valuation.marketCap],
      ['trailingPE', valuation.trailingPE],
      ['forwardPE', valuation.forwardPE],
      ['currentPrice', market.currentPrice],
      ['52wHigh', market.fiftyTwoWeekHigh],
      ['52wLow', market.fiftyTwoWeekLow],
    ].filter((row) => row[1] !== undefined && row[1] !== null && String(row[1]).trim() !== '');
    if (!rows.length) return '';
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(String(item?.ticker || 'n/a'))} company profile</span>
          <span class="pill">${safeText(String(item?.status || ''))}</span>
        </div>
        <div class="toolCardSummary">${safeText(String(item?.summary || ''))}</div>
        <div class="toolKv">
          ${rows
            .slice(0, 10)
            .map(
              (row) =>
                `<div class="k">${safeText(String(row[0]))}</div><div class="v">${safeText(formatMetric(row[1]))}</div>`,
            )
            .join('')}
        </div>
      </article>
    `;
  };

  const renderNewsCard = (item: any): string => {
    const payload = item?.payload && typeof item.payload === 'object' ? item.payload : {};
    const articles = Array.isArray(payload?.articles) ? payload.articles : [];
    if (!articles.length) return '';
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(String(item?.ticker || 'n/a'))} news</span>
          <span class="pill">${safeText(String(articles.length))} items</span>
        </div>
        <div class="toolCardSummary">${safeText(String(item?.summary || ''))}</div>
        <ol class="toolNewsList">
          ${articles
            .slice(0, 6)
            .map((article: any) => {
              const title = String(article?.title || article?.summary || '').trim() || '(untitled)';
              const url = String(article?.url || '').trim();
              const published = String(article?.published_at || '').trim();
              const titleHtml = url
                ? `<a href="${escapeHtmlAttr(sanitizeHref(url))}" target="_blank" rel="noopener">${safeText(title)}</a>`
                : safeText(title);
              return `<li>${titleHtml}${published ? ` <span class="muted">(${safeText(published)})</span>` : ''}</li>`;
            })
            .join('')}
        </ol>
      </article>
    `;
  };

  const renderFallbackCard = (item: any): string => {
    const tool = String(item?.tool || 'tool');
    const payload = item?.payload;
    const payloadText = payload ? safeText(JSON.stringify(payload).slice(0, 3000)) : '';
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(tool)}</span>
          <span class="pill">${safeText(String(item?.ticker || 'n/a'))}</span>
          <span class="pill">${safeText(String(item?.status || ''))}</span>
        </div>
        <div class="toolCardSummary">${safeText(String(item?.summary || ''))}</div>
        ${payloadText ? `<div class="chunkText">${payloadText}</div>` : ''}
      </article>
    `;
  };

  const cards: string[] = [];
  for (const item of list) {
    const tool = String(item?.tool || '').trim().toLowerCase();
    if (tool === 'yfinance_get_price_history') {
      cards.push(renderPriceChartCard(item) || renderFallbackCard(item));
      continue;
    }
    if (tool === 'yfinance_get_ticker_info') {
      cards.push(renderInfoCard(item) || renderFallbackCard(item));
      continue;
    }
    if (tool === 'yfinance_get_ticker_news') {
      cards.push(renderNewsCard(item) || renderFallbackCard(item));
      continue;
    }
    cards.push(renderFallbackCard(item));
  }
  els.toolResults.innerHTML = cards.join('');
}

/** Render streamed per-ticker briefs in dedicated cards. */
function renderPerTickerBriefs(briefs: Record<string, string>): void {
  const entries = Object.entries(briefs || {});
  if (els.briefsCountPill) els.briefsCountPill.textContent = String(entries.length);
  if (els.briefsStatus) {
    els.briefsStatus.textContent = entries.length
      ? `Showing ${entries.length} ticker brief${entries.length === 1 ? '' : 's'}.`
      : 'No per-ticker briefs yet.';
  }
  if (!els.briefsContainer) return;
  if (!entries.length) {
    els.briefsContainer.innerHTML = '';
    return;
  }
  const cards = entries
    .map(([ticker, text]) => {
      const body = String(text || '').trim();
      return `
        <article class="toolCard" style="margin-bottom: 0.6rem;">
          <div class="toolCardHead">
            <span class="toolCardTitle">${safeText(ticker)} brief</span>
            <span class="pill">${safeText(String(body.length))} chars</span>
          </div>
          <div class="answer markdown">${renderAnswerMarkdown(body, { citations: true })}</div>
        </article>
      `;
    })
    .join('');
  els.briefsContainer.innerHTML = cards;
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
    enable_refine: Boolean(els.enableRefine?.checked),
    top_k_retrieve: toInt(els.topKRetrieve.value, 30),
    top_k_rerank: toInt(els.topKRerank.value, 8),
    draft_max_tokens: toInt(els.draftMaxTokens.value, 65536),
    final_max_tokens: toInt(els.finalMaxTokens.value, 32768),
    brief_max_tokens: toInt(els.briefMaxTokens.value, 8000),
    answering_effort: String(els.answeringEffort?.value || 'medium').trim().toLowerCase() || 'medium',
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
  if (settings.brief_max_tokens) els.briefMaxTokens.value = settings.brief_max_tokens;
  if (els.answeringEffort) {
    const effort = String(settings.answering_effort || '').trim().toLowerCase();
    if (effort === 'low' || effort === 'medium' || effort === 'high') {
      els.answeringEffort.value = effort;
    }
  }
  if (els.enableRefine) {
    const hasExplicit = settings.enable_refine !== undefined && settings.enable_refine !== null;
    if (hasExplicit) els.enableRefine.checked = Boolean(settings.enable_refine);
    else els.enableRefine.checked = generationModes.modeUsesDraft(mode);
  }
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
  historyGroups = groupHistoryByConversation(historyItems);
  renderHistoryList({
    groups: historyGroups,
    filterValue: String(els.historyFilter?.value || ''),
    activeConversationKey,
    historyCountEl: els.historyCount,
    historyListEl: els.historyList,
    steps: STEP_ORDER,
    onSelect: (group) => {
      showConversation(group);
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

/** Build one HTML block with all turns from a selected conversation. */
function renderConversationThread(entriesNewestFirst: any[]): string {
  const ordered = [...entriesNewestFirst].reverse();
  const html = ordered.map((entry, idx) => {
    const turn = idx + 1;
    const createdAt = String(entry?.created_at || '').trim();
    const question = String(entry?.request?.question || '').trim() || '(missing question)';
    const res = entry?.response || {};
    const status = String(res?.status || 'answered').trim().toLowerCase();
    let answerText = String(res?.final_answer || '').trim();
    if (status === 'clarification_required' && !answerText) {
      answerText = String(res?.clarifying_question || '').trim();
    }
    if (status === 'refused' && !answerText) {
      answerText = 'The request was refused.';
    }
    if (!answerText) answerText = '(empty answer)';

    const statusClass = status === 'answered' ? 'ok' : status === 'refused' ? 'bad' : '';
    const answerHtml = renderAnswerMarkdown(answerText, { citations: true });
    return `
      <article class="turnCard" data-turn-index="${turn}">
        <div class="turnMeta">
          <span class="pill">turn ${turn}</span>
          ${status ? `<span class="pill ${statusClass}">${safeText(status)}</span>` : ''}
          ${createdAt ? `<span class="pill">${safeText(fmtDate(createdAt))}</span>` : ''}
        </div>
        <div class="turnQuestion">${safeText(question)}</div>
        <div class="turnAnswer markdown">${answerHtml}</div>
      </article>
    `;
  });
  return `<section class="conversationThread">${html.join('')}</section>`;
}

/** Return the active group object by its stable list key. */
function groupByKey(key: string | null): ConversationHistoryGroup | null {
  if (!key) return null;
  const found = historyGroups.find((group) => group.key === key);
  return found || null;
}

/** Return the active group object by conversation id. */
function groupByConversationId(conversationId: string | null): ConversationHistoryGroup | null {
  const cid = String(conversationId || '').trim();
  if (!cid) return null;
  const found = historyGroups.find((group) => group.conversation_id === cid);
  return found || null;
}

/** Keep active conversation selection stable after history refreshes. */
function syncActiveConversationAfterHistoryRefresh(): void {
  const fromConversationId = groupByConversationId(activeConversationId);
  if (fromConversationId) {
    showConversation(fromConversationId);
    return;
  }
  const fromKey = groupByKey(activeConversationKey);
  if (fromKey) {
    showConversation(fromKey);
    return;
  }
  if (!activeConversationKey && historyGroups.length) return;
  activeConversationKey = null;
  activeEntry = null;
}

/** Display a selected conversation in the main answer/debug panes. */
function showConversation(group: ConversationHistoryGroup, opts: { rerenderHistory?: boolean } = {}): void {
  const entry = group?.latest;
  if (!group || !entry) return;

  activeConversationKey = group.key;
  activeEntry = entry;
  activeConversationId = group.conversation_id;
  els.activeEntryPill.textContent = group.conversation_id
    ? `${group.conversation_id.slice(0, 8)} · ${group.entries.length} turn${group.entries.length === 1 ? '' : 's'}`
    : `entry · ${group.entries.length} turn${group.entries.length === 1 ? '' : 's'}`;
  if (opts.rerenderHistory !== false) renderHistory();

  const res = entry.response || {};
  const draft = String(res.draft_answer ?? '');
  const final = String(res.final_answer ?? '');
  const draftDiffers = Boolean(draft.trim() && draft.trim() !== final.trim());
  const shouldShowDraft = Boolean(entry?.request?.enable_refine) || draftDiffers;

  els.answerBlock.style.display = 'block';
  els.requestIdPill.textContent = entry.id ? 'hist ' + String(entry.id).slice(0, 8) : 'history';

  progressUi.reset();
  collapseProgressLog();
  progressUi.applyTimingMs(entry?.timing_ms || {});
  const bits = timingBits(entry?.timing_ms || {}, STEP_ORDER);
  if (bits.length) progressUi.append(`timings: ${bits.join(' · ')}`);

  setDraftPanelVisibility(shouldShowDraft);
  els.draftStatePill.textContent = 'done';

  citationManager.reset();
  const chunks = res.top_chunks || [];
  citationManager.updateFromChunks(chunks);

  if (shouldShowDraft) {
    els.draftAnswer.innerHTML = renderAnswerMarkdown(draft, { citations: true });
    if (draftDiffers && els.draftDetails) els.draftDetails.open = true;
  } else {
    els.draftAnswer.innerHTML = '';
  }
  renderToolResults(res.tool_results || []);
  els.finalAnswer.innerHTML = renderConversationThread(group.entries);

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
  activeConversationId = null;
  activeConversationKey = null;
  lastQueryResponse = null;
  citationManager.reset();
  lastRerankedChunks = [];
  lastRetrievedChunks = [];
  lastToolResults = [];

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
  collapseProgressLog();
  setDraftPanelVisibility(modeUsesDraft());
  els.draftStatePill.textContent = modeUsesDraft() ? 'waiting' : 'disabled';
  els.draftAnswer.innerHTML = '';
  renderToolResults([]);
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
  syncActiveConversationAfterHistoryRefresh();
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

/** Stop polling active ticker ingestion status. */
function stopIngestPolling(): void {
  if (activeIngestPollHandle !== null) {
    window.clearInterval(activeIngestPollHandle);
    activeIngestPollHandle = null;
  }
  activeIngestJobId = null;
}

/** Render ticker ingestion status controls from latest job payload. */
function renderIngestJobStatus(job: any): void {
  const status = String(job?.status || '').trim().toLowerCase() || 'idle';
  const stage = String(job?.stage || '').trim().toLowerCase();
  const tickers = Array.isArray(job?.tickers)
    ? job.tickers
        .map((item: unknown) => String(item || '').trim().toUpperCase())
        .filter((item: string) => Boolean(item))
    : [String(job?.ticker || '').trim().toUpperCase()].filter((item: string) => Boolean(item));
  const message = String(job?.message || '').trim();

  const running = status === 'queued' || status === 'running';
  els.ingestBtn.disabled = running;

  els.ingestJobPill.className = 'pill';
  if (status === 'succeeded') els.ingestJobPill.classList.add('ok');
  if (status === 'failed') els.ingestJobPill.classList.add('bad');
  els.ingestJobPill.textContent = status;

  const parts: string[] = [];
  if (tickers.length) parts.push(tickers.join(', '));
  if (stage) parts.push(stage);
  if (message) parts.push(message);
  els.ingestJobStatus.textContent = parts.length ? parts.join(' · ') : 'No active ingestion job.';
}

/** Poll backend until ticker ingestion reaches a terminal state. */
function startIngestPolling(jobId: string): void {
  stopIngestPolling();
  activeIngestJobId = String(jobId || '').trim();
  if (!activeIngestJobId) return;

  const poll = async (): Promise<void> => {
    if (!activeIngestJobId) return;
    try {
      const res = await fetch(`/ingest/${encodeURIComponent(activeIngestJobId)}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const job = await res.json();
      renderIngestJobStatus(job);

      const status = String(job?.status || '').trim().toLowerCase();
      if (status === 'succeeded' || status === 'failed') {
        stopIngestPolling();
        if (status === 'succeeded') void ingestedPanel.load();
      }
    } catch (e) {
      stopIngestPolling();
      els.ingestBtn.disabled = false;
      els.ingestJobPill.className = 'pill bad';
      els.ingestJobPill.textContent = 'failed';
      els.ingestJobStatus.textContent = 'Failed to poll ingestion status: ' + e;
    }
  };

  void poll();
  activeIngestPollHandle = window.setInterval(() => {
    void poll();
  }, 2000);
}

/** Normalize ticker text before submitting ingest request. */
function parseTickerInput(raw: unknown): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const text = String(raw || '').trim();
  if (!text) return out;

  const parts = text.split(/[\s,;]+/g);
  for (const part of parts) {
    const ticker = String(part || '').trim().toUpperCase();
    if (!ticker) continue;
    if (seen.has(ticker)) continue;
    seen.add(ticker);
    out.push(ticker);
  }
  return out;
}

/** Parse and validate files-per-company numeric control. */
function parsePerCompanyInput(raw: unknown): number | null {
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  const value = Math.floor(n);
  if (value <= 0) return null;
  return value;
}

/** Submit ticker ingestion request and begin job polling. */
async function startTickerIngestion(): Promise<void> {
  const tickers = parseTickerInput(els.ingestTicker.value);
  if (!tickers.length) {
    els.ingestJobPill.className = 'pill bad';
    els.ingestJobPill.textContent = 'failed';
    els.ingestJobStatus.textContent = 'At least one ticker is required.';
    return;
  }

  const perCompany = parsePerCompanyInput(els.ingestPerCompany.value);
  if (perCompany === null) {
    els.ingestJobPill.className = 'pill bad';
    els.ingestJobPill.textContent = 'failed';
    els.ingestJobStatus.textContent = 'Files/company must be a positive integer.';
    return;
  }

  els.ingestBtn.disabled = true;
  els.ingestJobPill.className = 'pill';
  els.ingestJobPill.textContent = 'starting';
  els.ingestJobStatus.textContent = `${tickers.join(', ')} · submitting request…`;

  try {
    const res = await fetch('/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers, per_company: perCompany }),
    });
    const payload = await res.json();
    if (!res.ok) {
      const detail = String(payload?.detail || '');
      throw new Error(detail || 'HTTP ' + res.status);
    }

    const jobId = String(payload?.job_id || '').trim();
    if (!jobId) throw new Error('Missing job_id in response.');

    els.ingestTicker.value = tickers.join(', ');
    renderIngestJobStatus(payload);
    startIngestPolling(jobId);
  } catch (e) {
    els.ingestBtn.disabled = false;
    els.ingestJobPill.className = 'pill bad';
    els.ingestJobPill.textContent = 'failed';
    els.ingestJobStatus.textContent = 'Failed to start ingestion: ' + e;
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
  const showDraft = modeUsesDraft(settings.mode, settings.enable_refine);
  writeSettings(settings);

  els.queryBtn.disabled = true;
  els.stopBtn.disabled = false;
  els.queryStatus.textContent = 'Starting…';
  els.copyAnswerBtn.disabled = true;
  els.copyDebugBtn.disabled = true;

  els.answerBlock.style.display = 'block';
  els.requestIdPill.textContent = '…';
  progressUi.reset();
  collapseProgressLog();
  progressUi.setSummary('running');
  setDraftPanelVisibility(showDraft);
  els.draftStatePill.textContent = showDraft ? 'waiting' : 'disabled';
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
  renderToolResults([]);
  renderPerTickerBriefs({});
  if (els.briefsDetails) {
    els.briefsDetails.hidden = true;
    els.briefsDetails.open = false;
  }

  let draftText = '';
  let finalText = '';
  const tickerBriefs: Record<string, string> = {};
  let sawDraftStage = false;
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
      body: JSON.stringify({ question, conversation_id: activeConversationId, ...settings }),
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
          const streamConversationId = String(evt?.conversation_id || '').trim();
          if (streamConversationId) activeConversationId = streamConversationId;
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
            sawDraftStage = true;
            setDraftPanelVisibility(true);
            els.draftStatePill.textContent = 'streaming';
            if (els.draftDetails) els.draftDetails.open = true;
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

        if (type === 'tool_results') {
          const results = Array.isArray(evt?.results) ? evt.results : [];
          renderToolResults(results);
          const ms = finishStep('tools', evt?.step_ms ?? evt?.tools_ms);
          const dur = formatDuration(ms, { empty: '' });
          const count = String(evt?.count ?? results.length);
          progressUi.append(dur ? `tools: ${dur} · ${count} results` : `Finance tools: ${count} results`);
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
            sawDraftStage = true;
            draftText += delta;
            setDraftPanelVisibility(true);
            if (els.draftDetails) els.draftDetails.open = true;
            scheduleDraftRender();
          }
          continue;
        }

        if (type === 'draft_done') {
          sawDraftStage = true;
          els.draftStatePill.textContent = 'done';
          const ms = finishStep('draft', evt?.step_ms ?? evt?.draft_ms);
          const dur = formatDuration(ms, { empty: '' });
          progressUi.append(dur ? `draft: ${dur} · ready` : 'Draft ready');
          continue;
        }

        if (type === 'briefs_start') {
          startStep('briefs');
          if (els.briefsDetails) {
            els.briefsDetails.hidden = false;
            els.briefsDetails.open = true;
          }
          renderPerTickerBriefs(tickerBriefs);
          continue;
        }

        if (type === 'ticker_brief_delta') {
          const ticker = String(evt?.ticker || '').trim().toUpperCase();
          const delta = String(evt?.delta || '');
          if (ticker && delta) {
            tickerBriefs[ticker] = String(tickerBriefs[ticker] || '') + delta;
            renderPerTickerBriefs(tickerBriefs);
          }
          continue;
        }

        if (type === 'ticker_brief_done') {
          const ticker = String(evt?.ticker || '').trim().toUpperCase();
          if (ticker && !tickerBriefs[ticker]) {
            tickerBriefs[ticker] = '';
          }
          renderPerTickerBriefs(tickerBriefs);
          continue;
        }

        if (type === 'briefs_done') {
          const ms = finishStep('briefs', evt?.step_ms ?? evt?.brief_ms);
          const dur = formatDuration(ms, { empty: '' });
          const count = String(evt?.count ?? Object.keys(tickerBriefs).length);
          progressUi.append(dur ? `briefs: ${dur} · ${count} briefs` : `Generated ${count} briefs`);
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
          expandProgressLog();
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
          expandProgressLog();
          break;
        }

        if (type === 'done') {
          const data = evt?.response || {};
          const responseStatus = String(data?.status || 'answered').trim().toLowerCase();
          const responseConversationId = String(data?.conversation_id || '').trim();
          if (responseConversationId) activeConversationId = responseConversationId;
          lastQueryResponse = data;
          if (responseStatus === 'clarification_required') {
            els.queryStatus.textContent = 'Clarification required.';
          } else if (responseStatus === 'refused') {
            els.queryStatus.textContent = 'Request refused.';
          } else {
            els.queryStatus.textContent = '';
          }

          const showDraftResult = responseStatus === 'answered' && (showDraft || sawDraftStage);
          setDraftPanelVisibility(showDraftResult);
          els.draftStatePill.textContent = showDraftResult ? 'done' : 'disabled';
          draftText = String(data.draft_answer ?? draftText);
          finalText = String(data.final_answer ?? finalText);
          renderToolResults(data.tool_results || []);
          renderPerTickerBriefs(tickerBriefs);
          citationManager.updateFromChunks(data.top_chunks || []);

          if (showDraftResult) {
            els.draftAnswer.innerHTML = renderAnswerMarkdown(draftText, { citations: true });
          } else {
            els.draftAnswer.innerHTML = '';
          }
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
          if (responseStatus === 'answered') {
            finishStep('final', evt?.final_ms ?? timing?.final_ms);
            if (Object.keys(timing).length) {
              progressUi.applyTimingMs(timing);
            } else {
              for (const step of STEP_ORDER) {
                if (!stepDurations.has(step)) progressUi.setStep(step, 'skipped', null);
              }
            }
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

          if (responseStatus === 'clarification_required') {
            progressUi.setSummary(`clarification ${formatDuration(total)}`);
          } else if (responseStatus === 'refused') {
            progressUi.setSummary(`refused ${formatDuration(total)}`, 'bad');
          } else {
            progressUi.setSummary(`total ${formatDuration(total)}`, 'ok');
          }
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
      expandProgressLog();
    } else {
      console.error(e);
      els.queryStatus.textContent = 'Error: ' + e;
      progressUi.setSummary('error', 'bad');
      progressUi.append('Error: ' + e);
      expandProgressLog();
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

/** Return concise fallback label when filing metadata is unavailable in chunk payload. */
function fallbackCitationLabel(docId: string): string {
  const doc = String(docId || '').trim();
  if (!doc) return 'citation';
  const short = doc.length > 14 ? `${doc.slice(0, 14)}...` : doc;
  return `doc ${short}`;
}

/** Pick the best chunk target from a chunk list for citation-driven source jumps. */
function chunkTargetFromList(chunks: any[], docId: string, chunkId: string): any | null {
  const list = Array.isArray(chunks) ? chunks : [];
  if (!list.length) return null;

  const wantedDoc = String(docId || '').trim();
  const wantedChunk = String(chunkId || '').trim();
  const match = wantedChunk
    ? list.find((chunk) => {
        const candidateChunk = String(chunk?.chunk_id || '').trim();
        if (candidateChunk !== wantedChunk) return false;
        const candidateDoc = String(chunk?.doc_id || '').trim();
        if (!wantedDoc) return true;
        return candidateDoc === wantedDoc;
      })
    : list.find((chunk) => String(chunk?.doc_id || '').trim() === wantedDoc);

  if (!match) return null;
  const src = String(match?.source || '').trim();
  const resolvedChunk = wantedChunk || String(match?.chunk_id || '').trim();
  if (!src || !resolvedChunk) return null;
  return {
    doc_id: wantedDoc || String(match?.doc_id || '').trim(),
    chunk_id: resolvedChunk,
    source: src,
    label: formatCitationLabelFromChunk(match) || fallbackCitationLabel(wantedDoc || String(match?.doc_id || '').trim()),
  };
}

/** Resolve citation target metadata across active chunk sets. */
function findChunkTargetForCitation(docId: string, chunkId: string): any | null {
  const d = String(docId || '').trim();
  const c = String(chunkId || '').trim();
  if (!d && !c) return null;

  const direct = citationManager.get(d, c);
  if (direct) return direct;

  const fromReranked = chunkTargetFromList(lastRerankedChunks, d, c);
  if (fromReranked) return fromReranked;
  const fromRetrieved = chunkTargetFromList(lastRetrievedChunks, d, c);
  if (fromRetrieved) return fromRetrieved;
  return chunkTargetFromList(lastQueryResponse?.top_chunks, d, c);
}

/** Open source viewer at citation target for the given document/chunk id pair. */
async function jumpToCitation(docId: string, chunkId: string): Promise<void> {
  const target = findChunkTargetForCitation(docId, chunkId);
  if (!target) return;
  const src = String(target.source || '').trim();
  const cid = String(target.chunk_id || '').trim();
  if (!src || !cid) return;

  els.sourceViewerDetails.open = true;
  els.sourceSelect.value = src;
  await sourceViewer.render(src, cid);
}

/** Handle clicks on citation links embedded in rendered answers. */
function onCitationClick(e: Event): void {
  const target = e.target as Element | null;
  const link = target?.closest?.('a.citationLink') as HTMLAnchorElement | null;
  if (!link) return;
  e.preventDefault();
  const docId = String(link.getAttribute('data-doc-id') || '').trim();
  const chunkId = String(link.getAttribute('data-chunk-id') || '').trim();
  void jumpToCitation(docId, chunkId);
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
    conversation_id: activeConversationId,
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
    briefMaxTokens: els.briefMaxTokens,
    answeringEffort: els.answeringEffort,
  });
  generationModes.updateModeHelp(mode, els.genModeHelp);
  if (els.enableRefine) els.enableRefine.checked = generationModes.modeUsesDraft(mode);
  const showDraft = modeUsesDraft(mode, els.enableRefine?.checked);
  setDraftPanelVisibility(showDraft);
  if (!showDraft) els.draftAnswer.innerHTML = '';
  if (!activeStream) els.draftStatePill.textContent = showDraft ? 'waiting' : 'disabled';
  writeSettings(currentSettings());
});
els.enableRefine?.addEventListener('change', () => {
  const showDraft = modeUsesDraft(undefined, els.enableRefine.checked);
  setDraftPanelVisibility(showDraft);
  if (!showDraft) els.draftAnswer.innerHTML = '';
  if (!activeStream) els.draftStatePill.textContent = showDraft ? 'waiting' : 'disabled';
  writeSettings(currentSettings());
});
[
  els.topKRetrieve,
  els.topKRerank,
  els.draftMaxTokens,
  els.finalMaxTokens,
  els.briefMaxTokens,
  els.answeringEffort,
].forEach((node) => {
  node?.addEventListener('change', () => {
    writeSettings(currentSettings());
  });
});

els.ingestedFilter?.addEventListener('input', () => {
  ingestedPanel.render();
});
els.ingestBtn?.addEventListener('click', () => {
  void startTickerIngestion();
});
els.ingestTicker?.addEventListener('keydown', (e: KeyboardEvent) => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  void startTickerIngestion();
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
      briefMaxTokens: els.briefMaxTokens,
      answeringEffort: els.answeringEffort,
    },
    { overwriteAdvanced: true },
  );
  generationModes.updateModeHelp(mode, els.genModeHelp);
  applySettings(saved);
  const showDraft = modeUsesDraft(mode, els.enableRefine?.checked);
  setDraftPanelVisibility(showDraft);
  if (!showDraft) {
    els.draftStatePill.textContent = 'disabled';
    els.draftAnswer.innerHTML = '';
  }
  collapseProgressLog();

  layout.applyUi(readUi());
  layout.setupSourcesSplitter();
  layout.setupAnswerSplitter();

  void sourceViewer.populateSourceSelect();
  void checkHealth();
  renderIngestJobStatus({ status: 'idle', stage: '', message: 'No active ingestion job.' });
  void ingestedPanel.load();
  void loadHistory();
})();
