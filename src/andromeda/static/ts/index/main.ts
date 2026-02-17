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

type PricePoint = {
  t: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
};

type ToolChartPayload = {
  ticker: string;
  title: string;
  summary: string;
  period: string;
  interval: string;
  points: PricePoint[];
};

type ToolStatementRow = {
  label: string;
  value: string;
};

const TOOL_DISPLAY_NAMES = new Map<string, string>([
  ['yfinance_get_price_history', 'Price history'],
  ['yfinance_get_ticker_info', 'Company profile'],
  ['yfinance_get_ticker_news', 'Recent news'],
  ['edgar_get_financial_metrics', 'SEC annual financial metrics'],
  ['edgar_get_quarterly_financial_metrics', 'SEC quarterly financial metrics'],
  ['edgar_get_financial_statements', 'SEC financial statements'],
]);

const TOOL_CHART_MODAL_WIDTH = 960;
const TOOL_CHART_MODAL_HEIGHT = 420;
const toolChartPayloadByKey = new Map<string, ToolChartPayload>();
let toolChartRenderVersion = 0;
let activeToolChartKey: string | null = null;
let activeToolChartHoverIndex: number | null = null;

/** Convert a value to finite number if possible, else `null`. */
function asNumber(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Return object payload when value is a plain object, else an empty object. */
function asPayloadObject(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {};
  return payload as Record<string, unknown>;
}

/** Return concise display label for a snake_case identifier. */
function titleCaseLabel(rawLabel: string): string {
  const text = String(rawLabel || '').trim().replace(/[_-]+/g, ' ');
  if (!text) return '';
  const acronymMap = new Map<string, string>([
    ['eps', 'EPS'],
    ['ebit', 'EBIT'],
    ['ebitda', 'EBITDA'],
    ['gaap', 'GAAP'],
    ['sec', 'SEC'],
    ['pe', 'P/E'],
    ['roe', 'ROE'],
    ['roa', 'ROA'],
    ['cagr', 'CAGR'],
  ]);
  return text
    .split(/\s+/g)
    .map((part) => {
      const lookup = acronymMap.get(part.toLowerCase());
      if (lookup) return lookup;
      if (/^\d+$/.test(part)) return part;
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    })
    .join(' ');
}

/** Return a polished display name for a tool identifier. */
function toolDisplayName(tool: string): string {
  const normalized = String(tool || '').trim().toLowerCase();
  const mapped = TOOL_DISPLAY_NAMES.get(normalized);
  if (mapped) return mapped;
  const fallback = titleCaseLabel(normalized);
  return fallback || 'Tool result';
}

/** Return formatted card title with ticker prefix when available. */
function toolCardTitle(item: any): string {
  const tool = String(item?.tool || '').trim().toLowerCase();
  const ticker = String(item?.ticker || '').trim().toUpperCase();
  const label = toolDisplayName(tool);
  return ticker ? `${ticker} ${label}` : label;
}

/** Return readable numeric/text value for compact UI tables. */
function formatMetricValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const abs = Math.abs(value);
    if (abs >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (typeof value === 'string') return value.trim();
  if (value === null || value === undefined) return '';
  return String(value);
}

/** Clamp number to inclusive min/max bounds. */
function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Return a short date label from ISO timestamp text. */
function formatChartDateLabel(rawTs: string): string {
  const text = String(rawTs || '').trim();
  if (!text) return 'n/a';
  const parsed = Date.parse(text);
  if (!Number.isFinite(parsed)) return text.slice(0, 10);
  return new Date(parsed).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** Return normalized OHLCV points from raw payload series list. */
function normalizePriceSeries(rawSeries: unknown): PricePoint[] {
  const series = Array.isArray(rawSeries) ? rawSeries : [];
  const out: PricePoint[] = [];
  for (const point of series) {
    const close = asNumber((point as any)?.close);
    if (close === null) continue;
    out.push({
      t: String((point as any)?.t || ''),
      open: asNumber((point as any)?.open),
      high: asNumber((point as any)?.high),
      low: asNumber((point as any)?.low),
      close,
      volume: asNumber((point as any)?.volume),
    });
  }
  return out;
}

/** Return true when series has complete OHLC values for candlestick view. */
function hasCandleData(points: PricePoint[]): boolean {
  return points.every((point) => point.open !== null && point.high !== null && point.low !== null);
}

/** Build two-column data table HTML with escaped content. */
function renderDataTable(
  headers: { left: string; right: string },
  rows: Array<{ left: string; right: string }>,
): string {
  if (!rows.length) return '';
  return `
    <div class="toolDataTableWrap">
      <table class="toolDataTable">
        <thead>
          <tr>
            <th>${safeText(headers.left)}</th>
            <th>${safeText(headers.right)}</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map((row) => `<tr><td>${safeText(row.left)}</td><td>${safeText(row.right)}</td></tr>`)
            .join('')}
        </tbody>
      </table>
    </div>
  `;
}

/** Render generic payload preview when no dedicated renderer exists. */
function renderFallbackPayload(payload: unknown): string {
  if (payload === null || payload === undefined) return '';
  if (typeof payload === 'string') {
    const text = payload.trim();
    if (!text) return '';
    const clipped = text.length > 1200 ? `${text.slice(0, 1200)}…` : text;
    return `<p class="toolPayloadText">${safeText(clipped)}</p>`;
  }

  if (typeof payload === 'number' && Number.isFinite(payload)) {
    return `<p class="toolPayloadText">${safeText(formatMetricValue(payload))}</p>`;
  }

  if (typeof payload === 'object' && !Array.isArray(payload)) {
    const rows = Object.entries(payload as Record<string, unknown>)
      .slice(0, 10)
      .map(([key, value]) => {
        const compact =
          value !== null && typeof value === 'object'
            ? JSON.stringify(value).slice(0, 120)
            : String(value ?? '').slice(0, 120);
        return { left: titleCaseLabel(key), right: compact };
      });
    return renderDataTable({ left: 'Field', right: 'Value' }, rows);
  }

  const compact = JSON.stringify(payload).slice(0, 1200);
  return compact ? `<p class="toolPayloadText">${safeText(compact)}</p>` : '';
}

/** Parse statement text into best-effort line item rows for readable display. */
function parseStatementRows(statementText: string, maxRows: number): ToolStatementRow[] {
  const rows: ToolStatementRow[] = [];
  const seen = new Set<string>();
  const numericPattern = /[\-($]?\d[\d,]*(?:\.\d+)?\)?/;
  const numericAllPattern = /[\-($]?\d[\d,]*(?:\.\d+)?\)?/g;

  for (const rawLine of String(statementText || '').split(/\r?\n/g)) {
    const line = rawLine.replace(/\|/g, ' ').replace(/\s+/g, ' ').trim();
    if (!line) continue;
    if (/^[-=:_\s]+$/.test(line)) continue;

    const firstNumeric = line.match(numericPattern);
    if (!firstNumeric || firstNumeric.index === undefined) continue;

    const label = line
      .slice(0, firstNumeric.index)
      .replace(/[.:;,\-–\s]+$/g, '')
      .trim();
    if (!label) continue;

    const numericTokens = line.match(numericAllPattern);
    if (!numericTokens || !numericTokens.length) continue;
    const valueToken = numericTokens[0];

    const key = label.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({ label, value: valueToken });
    if (rows.length >= maxRows) break;
  }
  return rows;
}

/** Return non-empty readable statement lines for fallback display. */
function parseStatementLines(statementText: string, maxLines: number): string[] {
  const lines: string[] = [];
  for (const rawLine of String(statementText || '').split(/\r?\n/g)) {
    const line = rawLine.replace(/\|/g, ' ').replace(/\s+/g, ' ').trim();
    if (!line) continue;
    if (/^[-=:_\s]+$/.test(line)) continue;
    lines.push(line);
    if (lines.length >= maxLines) break;
  }
  return lines;
}

/** Return active tool chart payload when modal has an open selection. */
function activeToolChartPayload(): ToolChartPayload | null {
  if (!activeToolChartKey) return null;
  return toolChartPayloadByKey.get(activeToolChartKey) || null;
}

/** Hide chart tooltip overlay in interactive modal. */
function hideToolChartTooltip(): void {
  if (!els.toolChartModalTooltip) return;
  els.toolChartModalTooltip.hidden = true;
  els.toolChartModalTooltip.textContent = '';
}

/** Draw active chart payload into interactive modal SVG. */
function renderToolChartModal(payload: ToolChartPayload, hoverIndex: number | null = null): void {
  if (!els.toolChartModalSvg) return;
  const points = payload.points;
  if (!points.length) {
    els.toolChartModalSvg.innerHTML = '';
    return;
  }

  const chartHasCandles = hasCandleData(points);
  const width = TOOL_CHART_MODAL_WIDTH;
  const height = TOOL_CHART_MODAL_HEIGHT;
  const padLeft = 66;
  const padRight = 16;
  const padTop = 16;
  const padBottom = 34;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;

  const highs = points.map((point) => (point.high === null ? point.close : point.high));
  const lows = points.map((point) => (point.low === null ? point.close : point.low));
  const minValue = Math.min(...lows);
  const maxValue = Math.max(...highs);
  const rawSpan = maxValue - minValue || 1;
  const yMin = minValue - rawSpan * 0.05;
  const yMax = maxValue + rawSpan * 0.05;
  const ySpan = yMax - yMin || 1;

  const xPos = points.map((_, idx) => padLeft + (plotWidth * idx) / Math.max(points.length - 1, 1));
  const toY = (value: number): number => padTop + ((yMax - value) / ySpan) * plotHeight;

  const gridLines = [0, 1, 2, 3, 4]
    .map((tick) => {
      const ratio = tick / 4;
      const y = padTop + ratio * plotHeight;
      const value = yMax - ratio * ySpan;
      return `
        <line x1="${padLeft}" y1="${y.toFixed(2)}" x2="${(width - padRight).toFixed(2)}" y2="${y.toFixed(2)}" stroke="rgba(41,70,93,0.15)" stroke-width="1"></line>
        <text x="${(padLeft - 8).toFixed(2)}" y="${(y + 4).toFixed(2)}" text-anchor="end" font-size="11" fill="#557088" font-family="var(--mono)">${safeText(formatMetricValue(value))}</text>
      `;
    })
    .join('');

  const xAxis = `
    <line x1="${padLeft}" y1="${(height - padBottom).toFixed(2)}" x2="${(width - padRight).toFixed(2)}" y2="${(height - padBottom).toFixed(2)}" stroke="rgba(41,70,93,0.24)" stroke-width="1"></line>
    <text x="${padLeft}" y="${(height - 10).toFixed(2)}" text-anchor="start" font-size="11" fill="#557088">${safeText(formatChartDateLabel(points[0].t))}</text>
    <text x="${(padLeft + plotWidth / 2).toFixed(2)}" y="${(height - 10).toFixed(2)}" text-anchor="middle" font-size="11" fill="#557088">${safeText(formatChartDateLabel(points[Math.floor(points.length / 2)].t))}</text>
    <text x="${(width - padRight).toFixed(2)}" y="${(height - 10).toFixed(2)}" text-anchor="end" font-size="11" fill="#557088">${safeText(formatChartDateLabel(points[points.length - 1].t))}</text>
  `;

  let seriesMarkup = '';
  if (chartHasCandles) {
    const candleWidth = clamp((plotWidth / Math.max(points.length, 1)) * 0.68, 3, 11);
    const candles = points.map((point, idx) => {
      const x = xPos[idx];
      const open = Number(point.open);
      const high = Number(point.high);
      const low = Number(point.low);
      const close = Number(point.close);
      const wickTop = toY(high);
      const wickBottom = toY(low);
      const openY = toY(open);
      const closeY = toY(close);
      const bodyTop = Math.min(openY, closeY);
      const bodyHeight = Math.max(Math.abs(closeY - openY), 1.2);
      const up = close >= open;
      const color = up ? '#0f766e' : '#be123c';
      return `
        <line x1="${x.toFixed(2)}" y1="${wickTop.toFixed(2)}" x2="${x.toFixed(2)}" y2="${wickBottom.toFixed(2)}" stroke="${color}" stroke-width="1.3"></line>
        <rect x="${(x - candleWidth / 2).toFixed(2)}" y="${bodyTop.toFixed(2)}" width="${candleWidth.toFixed(2)}" height="${bodyHeight.toFixed(2)}" fill="${color}" rx="1"></rect>
      `;
    });
    seriesMarkup = candles.join('');
  } else {
    const pointsAttr = points
      .map((point, idx) => `${xPos[idx].toFixed(2)},${toY(point.close).toFixed(2)}`)
      .join(' ');
    seriesMarkup = `<polyline points="${safeText(pointsAttr)}" fill="none" stroke="#0f766e" stroke-width="2.2"></polyline>`;
  }

  let hoverMarkup = '';
  if (hoverIndex !== null && hoverIndex >= 0 && hoverIndex < points.length) {
    const x = xPos[hoverIndex];
    const y = toY(points[hoverIndex].close);
    hoverMarkup = `
      <line x1="${x.toFixed(2)}" y1="${padTop}" x2="${x.toFixed(2)}" y2="${(height - padBottom).toFixed(2)}" stroke="rgba(14,116,144,0.45)" stroke-width="1" stroke-dasharray="3 3"></line>
      <line x1="${padLeft}" y1="${y.toFixed(2)}" x2="${(width - padRight).toFixed(2)}" y2="${y.toFixed(2)}" stroke="rgba(14,116,144,0.3)" stroke-width="1" stroke-dasharray="3 3"></line>
      <circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="3.2" fill="#0f766e" stroke="#ffffff" stroke-width="1"></circle>
    `;
  }

  els.toolChartModalSvg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="#f6fbff"></rect>
    ${gridLines}
    ${xAxis}
    ${seriesMarkup}
    ${hoverMarkup}
  `;

  if (els.toolChartModalTitle) els.toolChartModalTitle.textContent = payload.title;
  if (els.toolChartModalPeriodPill) els.toolChartModalPeriodPill.textContent = payload.period || 'period';
  if (els.toolChartModalIntervalPill) els.toolChartModalIntervalPill.textContent = payload.interval || 'interval';
  if (els.toolChartModalLegend) {
    els.toolChartModalLegend.textContent = chartHasCandles
      ? `Candlestick view · ${payload.points.length} sessions · hover for OHLC + volume.`
      : `Line view · ${payload.points.length} sessions · hover to inspect close values.`;
  }
}

/** Show tooltip content for a hovered point in the expanded chart modal. */
function showToolChartTooltip(payload: ToolChartPayload, index: number, event: MouseEvent): void {
  if (!els.toolChartModalTooltip || !els.toolChartModalPlotWrap) return;
  const point = payload.points[index];
  if (!point) return;

  const hasCandle = hasCandleData(payload.points);
  const bits = [`<div><b>${safeText(formatChartDateLabel(point.t))}</b></div>`, `<div>Close: ${safeText(formatMetricValue(point.close))}</div>`];
  if (hasCandle) {
    bits.push(`<div>Open: ${safeText(formatMetricValue(point.open))}</div>`);
    bits.push(`<div>High: ${safeText(formatMetricValue(point.high))}</div>`);
    bits.push(`<div>Low: ${safeText(formatMetricValue(point.low))}</div>`);
  }
  if (point.volume !== null) bits.push(`<div>Volume: ${safeText(formatMetricValue(point.volume))}</div>`);

  els.toolChartModalTooltip.innerHTML = bits.join('');
  els.toolChartModalTooltip.hidden = false;
  const wrapRect = els.toolChartModalPlotWrap.getBoundingClientRect();

  let left = event.clientX - wrapRect.left + 14;
  let top = event.clientY - wrapRect.top + 14;
  const maxLeft = wrapRect.width - els.toolChartModalTooltip.offsetWidth - 8;
  const maxTop = wrapRect.height - els.toolChartModalTooltip.offsetHeight - 8;

  left = clamp(left, 8, Math.max(8, maxLeft));
  top = clamp(top, 8, Math.max(8, maxTop));
  els.toolChartModalTooltip.style.left = `${left}px`;
  els.toolChartModalTooltip.style.top = `${top}px`;
}

/** Open interactive modal for a price chart card key. */
function openToolChartModal(chartKey: string): void {
  const key = String(chartKey || '').trim();
  if (!key) return;
  const payload = toolChartPayloadByKey.get(key);
  if (!payload || !els.toolChartModal) return;

  activeToolChartKey = key;
  activeToolChartHoverIndex = null;
  renderToolChartModal(payload);
  hideToolChartTooltip();
  els.toolChartModal.hidden = false;
  els.toolChartModal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('toolChartModalOpen');
}

/** Close interactive price chart modal and reset hover state. */
function closeToolChartModal(): void {
  if (!els.toolChartModal) return;
  activeToolChartKey = null;
  activeToolChartHoverIndex = null;
  hideToolChartTooltip();
  els.toolChartModal.hidden = true;
  els.toolChartModal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('toolChartModalOpen');
}

/** Render dedicated tool snapshot panel separate from markdown answer text. */
function renderToolResults(results: any[]): void {
  const list = Array.isArray(results) ? results : [];
  toolChartPayloadByKey.clear();
  toolChartRenderVersion += 1;
  lastToolResults = list;
  if (els.toolResultsCountPill) els.toolResultsCountPill.textContent = String(list.length);
  if (els.toolResultsStatus) {
    els.toolResultsStatus.textContent = list.length ? `Showing ${list.length} tool result${list.length === 1 ? '' : 's'}.` : 'No tool results yet.';
  }
  if (!els.toolResults) return;
  if (!list.length) {
    els.toolResults.innerHTML = '';
    if (activeToolChartKey) closeToolChartModal();
    return;
  }

  let chartIndex = 0;
  const renderMetaPills = (...values: Array<unknown>): string => {
    const pills = values
      .map((value) => String(value ?? '').trim())
      .filter((value) => Boolean(value))
      .map((value) => `<span class="pill">${safeText(value)}</span>`);
    if (!pills.length) return '';
    return `<div class="toolCardMeta">${pills.join('')}</div>`;
  };

  const renderPriceChartCard = (item: any): string => {
    const payload = asPayloadObject(item?.payload);
    const points = normalizePriceSeries(payload.series);
    if (!points.length) return '';

    const width = 360;
    const height = 130;
    const padX = 12;
    const padY = 11;
    const values = points.map((point) => Number(point.close));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const innerW = width - padX * 2;
    const innerH = height - padY * 2;
    const sparkline = points.map((point, idx) => {
      const x = padX + (innerW * idx) / Math.max(points.length - 1, 1);
      const y = padY + ((max - point.close) / span) * innerH;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    const first = Number(points[0]?.close);
    const last = Number(points[points.length - 1]?.close);
    const delta = last - first;
    const deltaPct = first === 0 ? 0 : (delta / first) * 100;
    const chartKey = `tool-chart-${toolChartRenderVersion}-${chartIndex}`;
    chartIndex += 1;
    toolChartPayloadByKey.set(chartKey, {
      ticker: String(item?.ticker || '').trim().toUpperCase(),
      title: toolCardTitle(item),
      summary: String(item?.summary || '').trim(),
      period: String(payload.period || 'period'),
      interval: String(payload.interval || 'interval'),
      points,
    });

    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(toolCardTitle(item))}</span>
          ${renderMetaPills(payload.period, payload.interval, item?.status)}
        </div>
        <p class="toolCardSummary">${safeText(String(item?.summary || ''))}</p>
        <button type="button" class="toolChartTrigger" data-chart-key="${escapeHtmlAttr(chartKey)}" aria-label="${escapeHtmlAttr(`Open interactive chart for ${toolCardTitle(item)}`)}">
          <svg class="toolChart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Price chart">
            <rect x="0" y="0" width="${width}" height="${height}" rx="10" ry="10" fill="#f5fafc"></rect>
            <polyline fill="none" stroke="#0f766e" stroke-width="2.2" points="${safeText(sparkline.join(' '))}"></polyline>
          </svg>
        </button>
        <div class="toolChartMeta">last ${formatMetricValue(last)} · min ${formatMetricValue(min)} · max ${formatMetricValue(max)} · ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} (${deltaPct.toFixed(2)}%)</div>
        <div class="toolChartHint">Click chart to enlarge and inspect detailed values.</div>
      </article>
    `;
  };

  const renderInfoCard = (item: any): string => {
    const payload = asPayloadObject(item?.payload);
    const profile = asPayloadObject(payload.profile);
    const valuation = asPayloadObject(payload.valuation);
    const market = asPayloadObject(payload.market);
    const rows = [
      ['Name', profile.longName],
      ['Sector', profile.sector],
      ['Industry', profile.industry],
      ['Market cap', valuation.marketCap],
      ['Trailing P/E', valuation.trailingPE],
      ['Forward P/E', valuation.forwardPE],
      ['Current price', market.currentPrice],
      ['52w high', market.fiftyTwoWeekHigh],
      ['52w low', market.fiftyTwoWeekLow],
    ].filter((row) => row[1] !== undefined && row[1] !== null && String(row[1]).trim() !== '');
    if (!rows.length) return '';
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(toolCardTitle(item))}</span>
          ${renderMetaPills(item?.status)}
        </div>
        <p class="toolCardSummary">${safeText(String(item?.summary || ''))}</p>
        <div class="toolKv">
          ${rows
            .slice(0, 10)
            .map(
              (row) =>
                `<div class="k">${safeText(String(row[0]))}</div><div class="v">${safeText(formatMetricValue(row[1]))}</div>`,
            )
            .join('')}
        </div>
      </article>
    `;
  };

  const renderNewsCard = (item: any): string => {
    const payload = asPayloadObject(item?.payload);
    const articles = Array.isArray(payload.articles) ? payload.articles : [];
    if (!articles.length) return '';
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(toolCardTitle(item))}</span>
          ${renderMetaPills(`${articles.length} items`, item?.status)}
        </div>
        <p class="toolCardSummary">${safeText(String(item?.summary || ''))}</p>
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

  const renderEdgarMetricsCard = (item: any): string => {
    const payload = asPayloadObject(item?.payload);
    const metrics = asPayloadObject(payload.metrics);
    const metricRows = Object.entries(metrics)
      .filter((entry) => {
        const value = entry[1];
        return value !== null && value !== undefined && String(value).trim() !== '';
      })
      .slice(0, 14)
      .map((entry) => ({ left: titleCaseLabel(entry[0]), right: formatMetricValue(entry[1]) }));
    if (!metricRows.length) return '';

    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(toolCardTitle(item))}</span>
          ${renderMetaPills(payload.period, item?.status)}
        </div>
        <p class="toolCardSummary">${safeText(String(item?.summary || ''))}</p>
        ${renderDataTable({ left: 'Metric', right: 'Value' }, metricRows)}
      </article>
    `;
  };

  const renderEdgarStatementsCard = (item: any): string => {
    const payload = asPayloadObject(item?.payload);
    const statementKeys = ['income_statement', 'balance_sheet', 'cashflow_statement'];
    const blocks = statementKeys
      .map((key) => {
        const statement = String(payload[key] || '').trim();
        if (!statement) return '';

        const rows = parseStatementRows(statement, 6);
        const title = titleCaseLabel(key);
        if (rows.length >= 3) {
          return `
            <section class="toolStatementBlock">
              <div class="toolStatementTitle">${safeText(title)}</div>
              ${renderDataTable(
                { left: 'Line item', right: 'Value' },
                rows.map((row) => ({ left: row.label, right: row.value })),
              )}
            </section>
          `;
        }

        const lines = parseStatementLines(statement, 6);
        if (!lines.length) return '';
        return `
          <section class="toolStatementBlock">
            <div class="toolStatementTitle">${safeText(title)}</div>
            <ul class="toolStatementLines">
              ${lines.map((line) => `<li>${safeText(line)}</li>`).join('')}
            </ul>
          </section>
        `;
      })
      .filter((block) => Boolean(block));

    if (!blocks.length) return '';
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(toolCardTitle(item))}</span>
          ${renderMetaPills(item?.status)}
        </div>
        <p class="toolCardSummary">${safeText(String(item?.summary || ''))}</p>
        <div class="toolStatementGrid">${blocks.join('')}</div>
      </article>
    `;
  };

  const renderFallbackCard = (item: any): string => {
    const payload = item?.payload ?? null;
    return `
      <article class="toolCard">
        <div class="toolCardHead">
          <span class="toolCardTitle">${safeText(toolCardTitle(item))}</span>
          ${renderMetaPills(item?.status)}
        </div>
        <p class="toolCardSummary">${safeText(String(item?.summary || ''))}</p>
        ${renderFallbackPayload(payload)}
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
    if (tool === 'edgar_get_financial_metrics' || tool === 'edgar_get_quarterly_financial_metrics') {
      cards.push(renderEdgarMetricsCard(item) || renderFallbackCard(item));
      continue;
    }
    if (tool === 'edgar_get_financial_statements') {
      cards.push(renderEdgarStatementsCard(item) || renderFallbackCard(item));
      continue;
    }
    cards.push(renderFallbackCard(item));
  }
  els.toolResults.innerHTML = cards.join('');

  if (activeToolChartKey && !toolChartPayloadByKey.has(activeToolChartKey)) {
    closeToolChartModal();
  }
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
    downloadJson('andromeda_history.json', items);
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
els.toolResults?.addEventListener('click', (event: Event) => {
  const target = event.target as Element | null;
  const trigger = target?.closest?.('button.toolChartTrigger') as HTMLButtonElement | null;
  if (!trigger) return;
  const chartKey = String(trigger.dataset.chartKey || '').trim();
  if (!chartKey) return;
  openToolChartModal(chartKey);
});

els.toolChartModalCloseBtn?.addEventListener('click', () => {
  closeToolChartModal();
});
els.toolChartModal?.addEventListener('click', (event: Event) => {
  const target = event.target as HTMLElement | null;
  if (!target) return;
  if (target.dataset.chartModalClose === '1') closeToolChartModal();
});
els.toolChartModalSvg?.addEventListener('mousemove', (event: MouseEvent) => {
  const payload = activeToolChartPayload();
  if (!payload || !payload.points.length || !els.toolChartModalSvg) return;

  const rect = els.toolChartModalSvg.getBoundingClientRect();
  if (!rect.width) return;
  const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  const hoverIndex = Math.round(ratio * Math.max(payload.points.length - 1, 1));
  if (activeToolChartHoverIndex !== hoverIndex) {
    activeToolChartHoverIndex = hoverIndex;
    renderToolChartModal(payload, hoverIndex);
  }
  showToolChartTooltip(payload, hoverIndex, event);
});
els.toolChartModalSvg?.addEventListener('mouseleave', () => {
  const payload = activeToolChartPayload();
  activeToolChartHoverIndex = null;
  hideToolChartTooltip();
  if (payload) renderToolChartModal(payload, null);
});
document.addEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key !== 'Escape') return;
  if (!els.toolChartModal || els.toolChartModal.hidden) return;
  closeToolChartModal();
});

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
