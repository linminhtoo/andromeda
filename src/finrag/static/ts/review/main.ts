import { els, state } from './dom.js';
import { renderCaseList, renderDetail } from './render.js';
import {
  fetchJSON,
  normalizeLabel,
  setSaveStatus,
  setStatus,
  syncJudgeToggleUI,
  updateURL,
} from './utils.js';

/** Load available eval runs and populate run selector dropdown. */
async function loadRuns(): Promise<void> {
  const data = await fetchJSON('/api/review/runs');
  state.runs = data.runs || [];
  els.runSelect.innerHTML = '';

  if (!state.runs.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No runs found';
    els.runSelect.appendChild(opt);
    return;
  }

  for (const run of state.runs) {
    const opt = document.createElement('option');
    opt.value = run.run_dir;
    opt.textContent = run.has_review_csv ? run.name : `${run.name} (no review.csv)`;
    if (!run.has_review_csv) opt.disabled = true;
    els.runSelect.appendChild(opt);
  }
}

/** Load review-case rows for selected run and refresh list pane. */
async function loadCases(runDir: string): Promise<void> {
  setStatus('Loading cases…', null);
  const data = await fetchJSON(`/api/review/cases?run_dir=${encodeURIComponent(runDir)}`);
  state.runDir = data.run_dir;
  state.cases = data.cases || [];
  state.selectedId = null;
  state.selectedDetail = null;
  renderCaseList(selectCase);
  setStatus(`Loaded ${state.cases.length} cases`, 'ok');
}

/** Fetch and render one case detail payload by query id. */
async function selectCase(queryId: string): Promise<void> {
  if (!queryId || queryId === state.selectedId) return;
  state.selectedId = queryId;
  renderCaseList(selectCase);
  setStatus('Loading case…', null);
  try {
    const detail = await fetchJSON(
      `/api/review/case?run_dir=${encodeURIComponent(state.runDir)}&query_id=${encodeURIComponent(queryId)}`,
    );
    state.selectedDetail = detail;
    renderDetail(detail);
    updateURL(state.runDir, queryId);
    setStatus('', null);
  } catch (e) {
    setStatus(String(e), 'bad');
  }
}

/** Debounce autosave when label/notes controls are edited. */
function scheduleAutoSave(): void {
  state.dirty = true;
  if (state.saveTimer) clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => {
    void saveCurrent(true);
  }, 700);
}

/** Persist current human label/notes to review CSV via API. */
async function saveCurrent(isAuto: boolean): Promise<void> {
  if (!state.selectedDetail || !state.selectedId) return;
  const qid = state.selectedId;
  const label = normalizeLabel(els.humanLabel.value);
  const notes = els.humanNotes.value || '';

  els.saveBtn.disabled = true;
  setSaveStatus(isAuto ? 'Autosaving…' : 'Saving…', null);

  try {
    await fetchJSON('/api/review/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_dir: state.runDir,
        query_id: qid,
        human_label: label === '' ? null : parseInt(label, 10),
        human_notes: notes,
      }),
    });

    const c = state.cases.find((x: any) => x.query_id === qid);
    if (c) c.human_label = label;
    if (state.selectedDetail && state.selectedDetail.review_row) {
      state.selectedDetail.review_row.human_label = label;
      state.selectedDetail.review_row.human_notes = notes;
    }

    renderCaseList(selectCase);
    setSaveStatus('Saved', 'ok');
    state.dirty = false;
  } catch (e) {
    setSaveStatus(String(e), 'bad');
  } finally {
    els.saveBtn.disabled = false;
  }
}

/** Resolve initial run selection from URL or first valid run. */
function getInitialRunDir(): string | null {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = String(params.get('run_dir') || '').trim();
  if (fromUrl) return fromUrl;
  const first = state.runs.find((r: any) => r.has_review_csv);
  return first ? first.run_dir : null;
}

/** Resolve initial query selection from URL parameters. */
function getInitialQueryId(): string | null {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = String(params.get('query_id') || '').trim();
  return fromUrl || null;
}

/** Bootstrap review app data, URL state, and first case selection. */
async function init(): Promise<void> {
  state.showJudge = (localStorage.getItem('finrag_review_show_judge') || '') === '1';
  syncJudgeToggleUI();

  try {
    await loadRuns();
  } catch (e) {
    setStatus(String(e), 'bad');
    return;
  }

  const runDir = getInitialRunDir();
  if (!runDir) {
    setStatus('No runnable eval runs found (need review.csv).', 'bad');
    return;
  }

  els.runSelect.value = runDir;
  if (els.runSelect.value !== runDir) {
    const opt = document.createElement('option');
    opt.value = runDir;
    opt.textContent = runDir;
    els.runSelect.insertBefore(opt, els.runSelect.firstChild);
    els.runSelect.value = runDir;
  }

  try {
    await loadCases(runDir);
  } catch (e) {
    setStatus(String(e), 'bad');
    return;
  }

  const wantId = getInitialQueryId();
  const firstId =
    wantId ||
    (state.filtered[0]
      ? state.filtered[0].query_id
      : state.cases[0]
        ? state.cases[0].query_id
        : null);
  if (firstId) await selectCase(firstId);
}

els.toggleJudgeBtn.addEventListener('click', () => {
  state.showJudge = !state.showJudge;
  localStorage.setItem('finrag_review_show_judge', state.showJudge ? '1' : '0');
  syncJudgeToggleUI();
  renderCaseList(selectCase);
  renderDetail(state.selectedDetail);
});

els.exportFailBtn.addEventListener('click', () => {
  const runDir = state.runDir || els.runSelect.value;
  if (!runDir) return;
  const url = `/api/review/export_jsonl?run_dir=${encodeURIComponent(runDir)}&label=1`;
  const a = document.createElement('a');
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
});

els.runSelect.addEventListener('change', async () => {
  const runDir = els.runSelect.value;
  if (!runDir) return;
  updateURL(runDir, null);
  try {
    await loadCases(runDir);
    if (state.cases[0]) await selectCase(state.cases[0].query_id);
  } catch (e) {
    setStatus(String(e), 'bad');
  }
});

els.reloadBtn.addEventListener('click', async () => {
  if (!state.runDir) return;
  try {
    await loadCases(state.runDir);
    if (state.cases[0]) await selectCase(state.cases[0].query_id);
  } catch (e) {
    setStatus(String(e), 'bad');
  }
});

els.search.addEventListener('input', () => renderCaseList(selectCase));
els.filterKind.addEventListener('change', () => renderCaseList(selectCase));
els.filterLabel.addEventListener('change', () => renderCaseList(selectCase));

els.saveBtn.addEventListener('click', () => {
  void saveCurrent(false);
});
els.humanLabel.addEventListener('change', () => scheduleAutoSave());
els.humanNotes.addEventListener('input', () => scheduleAutoSave());
els.humanNotes.addEventListener('keydown', (e: KeyboardEvent) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    void saveCurrent(false);
  }
});

window.addEventListener('beforeunload', (e: BeforeUnloadEvent) => {
  if (!state.dirty) return;
  e.preventDefault();
  e.returnValue = '';
});

void init();
