/** Build splitter/layout controller for sources width and answer/chunks height ratios. */
export function createLayoutController(opts: {
  els: any;
  readUi: () => any;
  writeUi: (patch: any) => void;
  defaultSourcesPaneWidthPx: number;
  defaultAnswerPanePct: number;
}) {
  const { els, readUi, writeUi, defaultSourcesPaneWidthPx, defaultAnswerPanePct } = opts;

  /** Clamp sources side pane width to responsive bounds. */
  const clampSourcesPaneWidth = (px: unknown): number => {
    const n = Number(px);
    if (!Number.isFinite(n)) return defaultSourcesPaneWidthPx;
    const rect = els.qaSplit?.getBoundingClientRect?.();
    const containerWidth = rect?.width || 0;
    const min = 320;
    const max = containerWidth ? Math.max(min, Math.floor(containerWidth * 0.7)) : 900;
    return Math.min(max, Math.max(min, Math.round(n)));
  };

  /** Apply sources pane width to CSS variable and ARIA metadata. */
  const setSourcesPaneWidth = (px: unknown): number | null => {
    if (!els.qaSplit) return null;
    const w = clampSourcesPaneWidth(px);
    els.qaSplit.style.setProperty('--sourcesPaneWidth', `${w}px`);
    if (els.qaSplitter) {
      els.qaSplitter.setAttribute('aria-valuenow', String(w));
      els.qaSplitter.setAttribute('aria-valuemin', '320');
    }
    return w;
  };

  /** Clamp answer pane percent to configured vertical split limits. */
  const clampAnswerPanePct = (pct: unknown): number => {
    const n = Number(pct);
    if (!Number.isFinite(n)) return defaultAnswerPanePct;
    return Math.min(90, Math.max(25, Math.round(n)));
  };

  /** Apply answer pane height ratio to CSS variable and ARIA metadata. */
  const setAnswerPanePct = (pct: unknown): number | null => {
    if (!els.answerSplit) return null;
    const clamped = clampAnswerPanePct(pct);
    els.answerSplit.style.setProperty('--answerPanePct', String(clamped));
    if (els.answerSplitter) els.answerSplitter.setAttribute('aria-valuenow', String(clamped));
    return clamped;
  };

  /** Restore persisted UI split values on startup. */
  const applyUi = (ui: any): void => {
    if (!els.qaSplit) return;

    const w = ui?.sourcesPaneWidthPx ?? ui?.sources_pane_width_px ?? null;
    const applied = setSourcesPaneWidth(Number(w) || defaultSourcesPaneWidthPx);
    if (els.qaSplitter && applied) {
      const rect = els.qaSplit.getBoundingClientRect();
      const max = rect?.width ? Math.max(320, Math.floor(rect.width * 0.7)) : 900;
      els.qaSplitter.setAttribute('aria-valuemax', String(max));
    }

    const answerPct = Number(ui?.answerPanePct ?? ui?.answer_pane_pct ?? defaultAnswerPanePct);
    if (els.answerSplit && Number.isFinite(answerPct)) {
      const clamped = clampAnswerPanePct(answerPct);
      els.answerSplit.style.setProperty('--answerPanePct', String(clamped));
      if (els.answerSplitter) {
        els.answerSplitter.setAttribute('aria-valuenow', String(clamped));
        els.answerSplitter.setAttribute('aria-valuemin', String(25));
        els.answerSplitter.setAttribute('aria-valuemax', String(90));
      }
    }
  };

  /** Wire pointer/keyboard handlers for horizontal QA/source splitter. */
  const setupSourcesSplitter = (): void => {
    if (!els.qaSplit || !els.qaSplitter) return;

    let dragging = false;
    const raw = getComputedStyle(els.qaSplit).getPropertyValue('--sourcesPaneWidth').trim();
    const match = raw.match(/(\d+)\s*px/);
    const initial = match ? Number(match[1]) : defaultSourcesPaneWidthPx;
    let lastAppliedWidth = setSourcesPaneWidth(initial) || defaultSourcesPaneWidthPx;

    const applyFromPointer = (clientX: number): void => {
      const rect = els.qaSplit.getBoundingClientRect();
      const rawWidth = rect.right - clientX;
      const applied = setSourcesPaneWidth(rawWidth);
      if (typeof applied === 'number') lastAppliedWidth = applied;
      els.qaSplitter.setAttribute('aria-valuemax', String(Math.max(320, Math.floor(rect.width * 0.7))));
    };

    const endDrag = (): void => {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove('resizing');
      writeUi({ sourcesPaneWidthPx: lastAppliedWidth });
    };

    els.qaSplitter.addEventListener('pointerdown', (e: PointerEvent) => {
      if (e.button !== 0) return;
      dragging = true;
      document.body.classList.add('resizing');
      try {
        els.qaSplitter.setPointerCapture(e.pointerId);
      } catch {
        // no-op
      }
      applyFromPointer(e.clientX);
    });
    els.qaSplitter.addEventListener('pointermove', (e: PointerEvent) => {
      if (!dragging) return;
      applyFromPointer(e.clientX);
    });
    els.qaSplitter.addEventListener('pointerup', () => endDrag());
    els.qaSplitter.addEventListener('pointercancel', () => endDrag());
    els.qaSplitter.addEventListener('dblclick', () => {
      lastAppliedWidth = setSourcesPaneWidth(defaultSourcesPaneWidthPx) || defaultSourcesPaneWidthPx;
      writeUi({ sourcesPaneWidthPx: lastAppliedWidth });
    });
    els.qaSplitter.addEventListener('keydown', (e: KeyboardEvent) => {
      const step = e.shiftKey ? 60 : 20;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        lastAppliedWidth = setSourcesPaneWidth(lastAppliedWidth + step) || lastAppliedWidth;
        writeUi({ sourcesPaneWidthPx: lastAppliedWidth });
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        lastAppliedWidth = setSourcesPaneWidth(lastAppliedWidth - step) || lastAppliedWidth;
        writeUi({ sourcesPaneWidthPx: lastAppliedWidth });
      }
    });

    window.addEventListener('resize', () => {
      lastAppliedWidth = setSourcesPaneWidth(lastAppliedWidth) || lastAppliedWidth;
    });
  };

  /** Wire pointer/keyboard handlers for vertical answer/chunks splitter. */
  const setupAnswerSplitter = (): void => {
    if (!els.answerSplit || !els.answerPane || !els.answerSplitter) return;

    let dragging = false;
    const initial = clampAnswerPanePct(readUi()?.answerPanePct ?? defaultAnswerPanePct);
    let lastAppliedPct = setAnswerPanePct(initial) || defaultAnswerPanePct;
    els.answerSplitter.setAttribute('aria-valuemin', String(25));
    els.answerSplitter.setAttribute('aria-valuemax', String(90));

    const applyFromPointer = (clientY: number): void => {
      const rect = els.answerSplit.getBoundingClientRect();
      const h = rect.height || 0;
      if (!h) return;
      const relative = (clientY - rect.top) / h;
      const pct = clampAnswerPanePct(relative * 100);
      const applied = setAnswerPanePct(pct);
      if (typeof applied === 'number') lastAppliedPct = applied;
    };

    const endDrag = (): void => {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove('resizingRow');
      writeUi({ answerPanePct: lastAppliedPct });
    };

    els.answerSplitter.addEventListener('pointerdown', (e: PointerEvent) => {
      if (e.button !== 0) return;
      dragging = true;
      document.body.classList.add('resizingRow');
      try {
        els.answerSplitter.setPointerCapture(e.pointerId);
      } catch {
        // no-op
      }
      applyFromPointer(e.clientY);
    });
    els.answerSplitter.addEventListener('pointermove', (e: PointerEvent) => {
      if (!dragging) return;
      applyFromPointer(e.clientY);
    });
    els.answerSplitter.addEventListener('pointerup', () => endDrag());
    els.answerSplitter.addEventListener('pointercancel', () => endDrag());
    els.answerSplitter.addEventListener('dblclick', () => {
      lastAppliedPct = setAnswerPanePct(defaultAnswerPanePct) || defaultAnswerPanePct;
      writeUi({ answerPanePct: lastAppliedPct });
    });
    els.answerSplitter.addEventListener('keydown', (e: KeyboardEvent) => {
      const step = e.shiftKey ? 8 : 3;
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        lastAppliedPct = setAnswerPanePct(lastAppliedPct + step) || lastAppliedPct;
        writeUi({ answerPanePct: lastAppliedPct });
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        lastAppliedPct = setAnswerPanePct(lastAppliedPct - step) || lastAppliedPct;
        writeUi({ answerPanePct: lastAppliedPct });
      }
    });
  };

  return {
    applyUi,
    setupSourcesSplitter,
    setupAnswerSplitter,
    setAnswerPanePct,
  };
}
