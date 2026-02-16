import { els, state } from './dom.js';
import { formatMs, judgePill, labelPill, normalizeLabel, timingMs } from './utils.js';

/** Render timing cards/summary from generation timing payload. */
export function renderTimingBlock(timing: any): void {
  const t = timing && typeof timing === 'object' ? timing : {};
  const retrieve = timingMs(t, 'retrieve_ms');
  const rerank = timingMs(t, 'rerank_ms');
  const draft = timingMs(t, 'draft_ms');
  const final = timingMs(t, 'final_ms');
  const total = timingMs(t, 'total_ms');
  const hasAny = [retrieve, rerank, draft, final, total].some((v) => v !== null);

  els.timingBlock.style.display = hasAny ? '' : 'none';
  if (!hasAny) return;

  els.timingRetrieve.textContent = formatMs(retrieve);
  els.timingRerank.textContent = formatMs(rerank);
  els.timingDraft.textContent = formatMs(draft);
  els.timingFinal.textContent = formatMs(final);
  els.timingTotalPill.textContent = total !== null ? `total ${formatMs(total)}` : 'timed';

  const bits: string[] = [];
  if (retrieve !== null) bits.push(`retrieve ${formatMs(retrieve)}`);
  if (rerank !== null) bits.push(`rerank ${formatMs(rerank)}`);
  if (draft !== null) bits.push(`draft ${formatMs(draft)}`);
  if (final !== null) bits.push(`final ${formatMs(final)}`);
  els.timingSummary.textContent = bits.join(' · ');
}

/** Apply active search + filter selections to case list state. */
function applyFilters(): void {
  const q = String(els.search.value || '').trim().toLowerCase();
  const kind = String(els.filterKind.value || '').trim();
  const lab = String(els.filterLabel.value || '').trim();

  const out: any[] = [];
  for (const c of state.cases) {
    if (kind && c.kind !== kind) continue;
    const cl = normalizeLabel(c.human_label);
    if (lab === 'unlabeled' && cl !== '') continue;
    if (lab === '0' && cl !== '0') continue;
    if (lab === '1' && cl !== '1') continue;
    if (q) {
      const hay = [c.question || '', c.tags || '', c.target_tickers || '', c.query_id || ''].join(' ').toLowerCase();
      if (!hay.includes(q)) continue;
    }
    out.push(c);
  }

  state.filtered = out;
}

/** Render retrieval/rerank chunk details for selected evaluation case. */
function renderChunks(container: HTMLElement, chunks: any[], opts: { goldChunkId?: string; goldDocId?: string } = {}): void {
  container.innerHTML = '';
  if (!Array.isArray(chunks) || !chunks.length) return;

  const goldChunkId = opts.goldChunkId ? String(opts.goldChunkId) : '';
  const goldDocId = opts.goldDocId ? String(opts.goldDocId) : '';

  chunks.forEach((ch, idx) => {
    const details = document.createElement('details');
    const isGold = (goldChunkId && ch.chunk_id === goldChunkId) ||
      (goldDocId && ch.doc_id === goldDocId && ch.chunk_id === goldChunkId);
    if (isGold) details.classList.add('chunkGold');

    const summary = document.createElement('summary');
    const left = document.createElement('span');
    left.textContent = `#${idx + 1}  score=${typeof ch.score === 'number' ? ch.score.toFixed(4) : ch.score}`;

    const right = document.createElement('span');
    const doc = ch.metadata && ch.metadata.doc ? ch.metadata.doc : {};
    const bits: string[] = [];
    if (doc.ticker) bits.push(doc.ticker);
    if (doc.filing_type) bits.push(doc.filing_type);
    if (doc.filing_date) bits.push(doc.filing_date);
    right.textContent = bits.join(' • ') || (ch.doc_id ? String(ch.doc_id).slice(0, 8) : '');

    summary.appendChild(left);
    summary.appendChild(right);
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'chunkBody';

    const meta = document.createElement('div');
    meta.className = 'chunkMeta';

    const mono1 = document.createElement('span');
    mono1.className = 'pill';
    mono1.textContent = ch.chunk_id ? `chunk ${String(ch.chunk_id).slice(0, 16)}` : 'chunk';
    meta.appendChild(mono1);

    if (ch.page_no !== null && ch.page_no !== undefined && ch.page_no !== '') {
      const pg = document.createElement('span');
      pg.className = 'pill';
      pg.textContent = `page ${ch.page_no}`;
      meta.appendChild(pg);
    }

    if (ch.source) {
      const a = document.createElement('a');
      a.href = `/source?path=${encodeURIComponent(ch.source)}`;
      a.target = '_blank';
      a.rel = 'noreferrer';
      a.textContent = 'open source';
      meta.appendChild(a);
    }

    body.appendChild(meta);

    if (ch.context) {
      const ctx = document.createElement('div');
      ctx.className = 'muted';
      ctx.style.marginBottom = '0.6rem';
      ctx.textContent = String(ch.context);
      body.appendChild(ctx);
    }

    const text = document.createElement('div');
    text.className = 'code chunkText';
    text.textContent = String(ch.text || ch.preview || '');
    body.appendChild(text);

    details.appendChild(body);
    container.appendChild(details);
  });
}

/** Toggle between placeholder and detail content panels. */
function setDetailVisible(on: boolean): void {
  els.detailEmpty.style.display = on ? 'none' : 'block';
  els.detailContent.style.display = on ? 'block' : 'none';
}

/** Render left-pane case list with counts, labels, and judge info. */
export function renderCaseList(selectCase: (queryId: string) => Promise<void>): void {
  els.caseList.innerHTML = '';
  applyFilters();

  const n = state.cases.length;
  const nPass = state.cases.filter((c: any) => normalizeLabel(c.human_label) === '0').length;
  const nFail = state.cases.filter((c: any) => normalizeLabel(c.human_label) === '1').length;
  const nUnl = n - nPass - nFail;
  els.caseCounts.textContent = `total ${n} • pass ${nPass} • fail ${nFail} • unlabeled ${nUnl}`;

  if (!state.filtered.length) {
    const empty = document.createElement('div');
    empty.className = 'caseItem';
    empty.innerHTML = '<div class="muted">No cases match current filters.</div>';
    els.caseList.appendChild(empty);
    return;
  }

  for (const c of state.filtered) {
    const item = document.createElement('div');
    item.className = 'caseItem' + (c.query_id === state.selectedId ? ' active' : '');
    item.dataset.qid = c.query_id;

    const q = document.createElement('div');
    q.className = 'caseQ';
    q.textContent = c.question || '(missing question)';
    item.appendChild(q);

    const meta = document.createElement('div');
    meta.className = 'caseMeta';

    const lp = labelPill(c.human_label);
    const p1 = document.createElement('span');
    p1.className = 'pill ' + (lp.cls || '');
    p1.textContent = lp.text;
    meta.appendChild(p1);

    const p2 = document.createElement('span');
    p2.className = 'pill kind';
    p2.textContent = c.kind || '';
    meta.appendChild(p2);

    if (state.showJudge && c.judge_prediction) {
      const jp = judgePill(c.judge_prediction);
      const pj = document.createElement('span');
      pj.className = 'pill ' + (jp.cls || '');
      pj.textContent = jp.text;
      meta.appendChild(pj);
    }

    if (c.target_tickers) {
      const p3 = document.createElement('span');
      p3.className = 'pill';
      p3.textContent = c.target_tickers;
      meta.appendChild(p3);
    }

    if (c.has_error) {
      const pe = document.createElement('span');
      pe.className = 'pill err';
      pe.textContent = 'error';
      meta.appendChild(pe);
    }

    item.appendChild(meta);
    item.addEventListener('click', () => {
      void selectCase(c.query_id);
    });
    els.caseList.appendChild(item);
  }
}

/** Render full selected-case detail view, answers, timings, and chunks. */
export function renderDetail(detail: any): void {
  if (!detail) {
    setDetailVisible(false);
    renderTimingBlock(null);
    return;
  }

  setDetailVisible(true);
  const row = detail.review_row || {};
  const gen = detail.generation || {};

  els.activeId.textContent = detail.query_id || '—';
  els.activeKind.textContent = row.kind || '—';

  els.questionText.textContent = row.question || '';
  els.metaTags.textContent = row.tags ? `tags: ${row.tags}` : 'tags: —';
  els.metaTickers.textContent = row.target_tickers ? `tickers: ${row.target_tickers}` : 'tickers: —';
  if (state.showJudge) {
    const jp = judgePill(row.judge_prediction || '');
    els.metaJudge.textContent = jp.text;
    els.metaJudge.className = 'pill ' + (jp.cls || '');
    els.metaJudge.style.display = '';
  } else {
    els.metaJudge.style.display = 'none';
  }

  els.finalAnswer.textContent = gen.final_answer || row.final_answer || '';
  els.draftAnswer.textContent = gen.draft_answer || '';
  renderTimingBlock(gen.timing_ms || null);

  els.humanLabel.value = normalizeLabel(row.human_label);
  els.humanNotes.value = row.human_notes || '';
  state.dirty = false;

  if (state.showJudge) {
    els.judgeBlock.style.display = '';
    const jp = judgePill(row.judge_prediction || '');
    els.judgePredPill.textContent = jp.text.replace('judge: ', '');
    els.judgePredPill.className = 'pill ' + (jp.cls || '');
    els.judgeIdPill.textContent = row.judge_id ? `judge_id: ${row.judge_id}` : 'judge_id: —';
    els.judgeExplanation.textContent = row.judge_explanation || '(no explanation recorded)';
  } else {
    els.judgeBlock.style.display = 'none';
  }

  const goldChunkId = row.gold_chunk_id || '';
  const goldDocId = row.gold_doc_id || '';

  const reranked = Array.isArray(gen.top_chunks) ? gen.top_chunks : [];
  els.rerankedEmpty.style.display = reranked.length ? 'none' : 'block';
  renderChunks(els.chunksReranked, reranked, { goldChunkId, goldDocId });

  const retrieved = Array.isArray(gen.retrieved_chunks) ? gen.retrieved_chunks : [];
  els.retrievedCountPill.textContent = retrieved.length ? `${retrieved.length} chunks` : '—';
  els.retrievedEmpty.style.display = retrieved.length ? 'none' : 'block';
  renderChunks(els.chunksRetrieved, retrieved, { goldChunkId, goldDocId });
}
