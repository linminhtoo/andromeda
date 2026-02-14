import { safeText } from '../shared/html.js';

/** Return true when source path is markdown/text renderable in-app. */
export function isMarkdownSource(source: unknown): boolean {
  const s = String(source || '').trim().toLowerCase();
  return s.endsWith('.md') || s.endsWith('.markdown') || s.endsWith('.txt');
}

/** Group chunks by source document path for viewer dropdown/rendering. */
export function buildChunksBySource(chunks: any[]): Map<string, any[]> {
  const map = new Map<string, any[]>();
  (Array.isArray(chunks) ? chunks : []).forEach((chunk) => {
    const src = String(chunk?.source || '').trim();
    if (!src) return;
    if (!map.has(src)) map.set(src, []);
    map.get(src)?.push(chunk);
  });
  return map;
}

/** Normalize text and retain index mapping for fuzzy span search. */
function normalizeForSearchWithMap(text: string): { norm: string; map: number[] } {
  const src = String(text ?? '');
  const out: string[] = [];
  const map: number[] = [];
  let lastWasSpace = true;

  const isWord = (ch: string): boolean => {
    if (!ch) return false;
    const code = ch.charCodeAt(0);
    if (code >= 48 && code <= 57) return true;
    if (code >= 65 && code <= 90) return true;
    if (code >= 97 && code <= 122) return true;
    return ch.toLowerCase() !== ch.toUpperCase();
  };

  const asSpace = (ch: string): boolean => {
    if (!ch) return true;
    if (/\s/.test(ch)) return true;
    return ch === '|' || ch === '-' || ch === '—' || ch === '_' || ch === '/' || ch === '\\' || ch === ':' || ch === ';';
  };

  for (let i = 0; i < src.length; i += 1) {
    const raw = src[i];
    const ch = raw.toLowerCase();
    if (isWord(ch)) {
      out.push(ch);
      map.push(i);
      lastWasSpace = false;
      continue;
    }
    if (!lastWasSpace && asSpace(ch)) {
      out.push(' ');
      map.push(i);
      lastWasSpace = true;
      continue;
    }
    if (!lastWasSpace && !asSpace(ch)) {
      out.push(' ');
      map.push(i);
      lastWasSpace = true;
    }
  }

  while (out.length && out[out.length - 1] === ' ') {
    out.pop();
    map.pop();
  }

  return { norm: out.join(''), map };
}

/** Create best-effort snippet finder tolerant to formatting drift. */
function makeSpanFinder(text: string): (snippet: string) => { start: number; end: number } | null {
  const hay = String(text ?? '');
  const hayNorm = normalizeForSearchWithMap(hay);

  return (snippet: string) => {
    let needle = String(snippet ?? '').trim();
    if (!hay || !needle) return null;

    if (needle.length > 420) needle = needle.slice(0, 420);

    let idx = hay.indexOf(needle);
    if (idx >= 0) return { start: idx, end: idx + needle.length };

    const tokens = needle.split(/\s+/).filter(Boolean).slice(0, 30);
    if (tokens.length >= 6) {
      const escapeRe = (token: string): string => token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const pattern = tokens.map(escapeRe).join('\\s+');
      const re = new RegExp(pattern, 'm');
      const match = re.exec(hay);
      if (match && typeof match.index === 'number') return { start: match.index, end: match.index + match[0].length };
    }

    const needleNorm = normalizeForSearchWithMap(needle).norm;
    const normalizedNeedle = needleNorm.length > 520 ? needleNorm.slice(0, 520) : needleNorm;
    if (normalizedNeedle.length >= 60) {
      idx = hayNorm.norm.indexOf(normalizedNeedle);
      if (idx >= 0) {
        const start = hayNorm.map[idx] ?? 0;
        const endIdx = hayNorm.map[idx + normalizedNeedle.length - 1];
        const end = typeof endIdx === 'number' ? endIdx + 1 : Math.min(hay.length, start + needle.length);
        return { start, end };
      }
    }

    if (needle.length > 80) {
      const shortNeedle = needle.slice(0, 80);
      idx = hay.indexOf(shortNeedle);
      if (idx >= 0) return { start: idx, end: idx + shortNeedle.length };
    }

    return null;
  };
}

/** Render raw source text with `<mark>` spans for matched chunk snippets. */
function renderTextWithMarks(
  text: string,
  spans: Array<{ start: number; end: number; chunk_id: string }> | undefined,
  activeChunkId: string | null,
): string {
  const src = String(text ?? '');
  const safeSpans = (Array.isArray(spans) ? spans : [])
    .filter((span) => span && Number.isFinite(span.start) && Number.isFinite(span.end) && span.start >= 0 && span.end > span.start)
    .sort((a, b) => a.start - b.start);

  const merged: Array<{ start: number; end: number; chunk_id: string }> = [];
  let lastEnd = -1;
  for (const span of safeSpans) {
    if (span.start < lastEnd) continue;
    merged.push(span);
    lastEnd = span.end;
  }

  let out = '';
  let pos = 0;
  for (const span of merged) {
    out += safeText(src.slice(pos, span.start));
    const chunkId = String(span.chunk_id || '');
    const cls = chunkId && activeChunkId && chunkId === activeChunkId ? 'active' : '';
    out += `<mark class="${cls}" data-chunk-id="${safeText(chunkId)}">${safeText(src.slice(span.start, span.end))}</mark>`;
    pos = span.end;
  }
  out += safeText(src.slice(pos));
  return out;
}

/** Respect OS/browser reduced motion preference for viewer scroll animation. */
function prefersReducedMotion(): boolean {
  try {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch {
    return false;
  }
}

/** Animate scroll container to target top offset. */
function fastScrollContainerTo(container: HTMLElement, targetTop: number, { durationMs = 140 }: { durationMs?: number } = {}): void {
  const maxTop = Math.max(0, (container.scrollHeight || 0) - (container.clientHeight || 0));
  const to = Math.min(maxTop, Math.max(0, Number(targetTop) || 0));
  const from = Number(container.scrollTop) || 0;
  const delta = to - from;
  if (!delta) return;

  if (prefersReducedMotion() || durationMs <= 0) {
    container.scrollTop = to;
    return;
  }

  const start = performance.now();
  const easeOutCubic = (t: number): number => 1 - Math.pow(1 - t, 3);
  const tick = (now: number): void => {
    const t = Math.min(1, (now - start) / durationMs);
    container.scrollTop = from + delta * easeOutCubic(t);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** Scroll matched mark element into view inside the source viewer pane. */
function fastScrollElementIntoView(
  container: HTMLElement,
  element: Element,
  { block = 'center', durationMs = 140 }: { block?: 'start' | 'center' | 'end'; durationMs?: number } = {},
): void {
  const c = container.getBoundingClientRect();
  const r = element.getBoundingClientRect();
  const currentTop = Number(container.scrollTop) || 0;
  const topDelta = r.top - c.top;
  let desiredTop = currentTop + topDelta;
  if (block === 'center') desiredTop = desiredTop - c.height / 2 + r.height / 2;
  if (block === 'end') desiredTop = desiredTop - c.height + r.height;
  fastScrollContainerTo(container, desiredTop, { durationMs });
}

/** Control source-document viewing, highlighting, and mode toggling. */
export class SourceViewer {
  private sourceMode: 'raw' | 'rendered' = 'raw';
  private chunksBySource = new Map<string, any[]>();
  private sourceCache = new Map<string, any>();

  constructor(
    private deps: {
      els: any;
      renderMarkdown: (md: string) => string;
      extractDocMeta: (chunk: any) => any | null;
      formatDocMetaLine: (doc: any) => string;
    },
  ) {}

  /** Replace chunk grouping used for document selector + highlighting. */
  setChunksBySource(chunksBySource: Map<string, any[]>): void {
    this.chunksBySource = chunksBySource;
  }

  /** Return currently indexed chunk grouping by source path. */
  getChunksBySource(): Map<string, any[]> {
    return this.chunksBySource;
  }

  /** Clear current source/chunk context after reset/new query. */
  clearChunks(): void {
    this.chunksBySource = new Map();
  }

  /** Return current display mode (`raw` or `rendered`). */
  getMode(): 'raw' | 'rendered' {
    return this.sourceMode;
  }

  /** Toggle display mode and return the new mode value. */
  toggleMode(): 'raw' | 'rendered' {
    this.sourceMode = this.sourceMode === 'raw' ? 'rendered' : 'raw';
    return this.sourceMode;
  }

  /** Force re-fetch of active source document text from backend. */
  async reloadCurrent(): Promise<void> {
    const src = String(this.deps.els.sourceSelect?.value || '').trim();
    if (!src) return;
    this.sourceCache.delete(src);
    await this.render(src, null);
  }

  /** Rebuild source selector options from current chunk grouping. */
  async populateSourceSelect(): Promise<void> {
    const { els } = this.deps;
    const sources = Array.from(this.chunksBySource.keys()).filter(isMarkdownSource);
    const prev = String(els.sourceSelect.value || '').trim();
    els.sourceSelect.innerHTML = '';

    sources.forEach((src) => {
      const opt = document.createElement('option');
      const count = (this.chunksBySource.get(src) || []).length;
      opt.value = src;
      opt.textContent = `${src} (${count})`;
      els.sourceSelect.appendChild(opt);
    });

    els.sourceCountPill.textContent = `${sources.length} docs`;

    if (!sources.length) {
      els.sourceSelect.disabled = true;
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'No markdown sources in current results';
      els.sourceSelect.appendChild(opt);
      await this.render('', null);
      return;
    }

    els.sourceSelect.disabled = false;
    const selected = sources.includes(prev) ? prev : sources[0];
    els.sourceSelect.value = selected;
    await this.render(selected, null);
  }

  /** Render selected source in current mode and optionally focus chunk match. */
  async render(source: string, activeChunkId: string | null): Promise<void> {
    const { els, extractDocMeta, formatDocMetaLine, renderMarkdown } = this.deps;
    const src = String(source || '').trim();
    if (!src || !isMarkdownSource(src)) {
      els.sourceModePill.textContent = this.sourceMode;
      els.sourceStatus.textContent = '';
      if (els.sourceMeta) els.sourceMeta.innerHTML = '';
      els.sourceContent.innerHTML = '<div class="muted">Select a markdown source to view it here.</div>';
      return;
    }

    const chunksForSrc = this.chunksBySource.get(src) || [];
    const doc = extractDocMeta(chunksForSrc[0]);
    const docLine = formatDocMetaLine(doc);
    if (els.sourceMeta) els.sourceMeta.innerHTML = docLine ? docLine : '';

    els.sourceStatus.textContent = 'Loading…';
    try {
      const data = await this.loadSourceText(src);
      const text = String(data.text ?? '');
      const chunks = chunksForSrc;

      const findSpan = makeSpanFinder(text);
      const spans: Array<{ start: number; end: number; chunk_id: string }> = [];
      for (const chunk of chunks) {
        const chunkId = String(chunk?.chunk_id || '');
        const snippet = String(chunk?.text || chunk?.preview || '').trim();
        if (!chunkId || !snippet) continue;
        const span = findSpan(snippet);
        if (!span) continue;
        spans.push({ ...span, chunk_id: chunkId });
      }

      if (this.sourceMode === 'rendered') {
        els.sourceModePill.textContent = 'rendered';
        els.sourceContent.classList.add('markdown');
        els.sourceContent.innerHTML = renderMarkdown(text);
        els.sourceStatus.textContent = 'Rendered (highlighting is raw-only)';
      } else {
        els.sourceModePill.textContent = 'raw';
        els.sourceContent.classList.remove('markdown');
        els.sourceContent.innerHTML = renderTextWithMarks(text, spans, activeChunkId);
        els.sourceStatus.textContent = spans.length ? `Highlighted ${spans.length} matches` : 'No matches found';

        if (activeChunkId) {
          const selector = `mark[data-chunk-id="${CSS.escape(activeChunkId)}"]`;
          const mark = els.sourceContent.querySelector(selector);
          if (mark) fastScrollElementIntoView(els.sourceContent, mark, { block: 'center', durationMs: 140 });
        }
      }
    } catch (e) {
      console.error(e);
      els.sourceStatus.textContent = 'Error';
      els.sourceContent.innerHTML = `<div class="muted">Failed to load source: ${safeText(e)}</div>`;
    }
  }

  /** Fetch and cache source text payload from backend endpoint. */
  private async loadSourceText(source: string): Promise<any> {
    const src = String(source || '').trim();
    if (!src) throw new Error('Missing source');
    if (this.sourceCache.has(src)) return this.sourceCache.get(src);
    const res = await fetch('/source_text?path=' + encodeURIComponent(src));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    this.sourceCache.set(src, data);
    return data;
  }
}
