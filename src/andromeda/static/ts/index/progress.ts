import { formatDuration } from '../shared/time.js';

/** Parse a timing field as a non-negative millisecond value. */
export function getTimingMs(timing: any, key: string): number | null {
  const n = Number(timing?.[key]);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** Build per-step timing strings for history/progress summaries. */
export function timingBits(timing: any, steps: string[]): string[] {
  const bits: string[] = [];
  for (const step of steps) {
    const ms = getTimingMs(timing, `${step}_ms`);
    if (ms === null) continue;
    bits.push(`${step} ${formatDuration(ms)}`);
  }
  return bits;
}

/** Handle progress pipeline + event feed rendering for streaming queries. */
export class ProgressUI {
  /** Controller for step pipeline + activity feed widgets in the Q&A UI. */
  constructor(
    private readonly els: {
      summary: HTMLElement;
      pipeline: HTMLElement;
      log: HTMLElement;
    },
    private readonly stepOrder: string[],
  ) {}

  /** Update the top summary pill text and semantic style. */
  setSummary(text: string, kind?: 'ok' | 'bad'): void {
    this.els.summary.textContent = String(text || 'waiting');
    this.els.summary.className = 'pill';
    if (kind === 'ok') this.els.summary.classList.add('ok');
    if (kind === 'bad') this.els.summary.classList.add('bad');
  }

  /** Update a single pipeline step state and optional duration label. */
  setStep(step: string, state: 'pending' | 'running' | 'done' | 'error' | 'skipped', ms: number | null): void {
    const node = this.els.pipeline.querySelector(`.progressStep[data-step="${step}"]`);
    if (!node) return;

    node.setAttribute('data-state', state);

    const stateEl = node.querySelector('.progressStepState') as HTMLElement | null;
    const timeEl = node.querySelector('.progressStepTime') as HTMLElement | null;

    if (stateEl) {
      if (state === 'running') stateEl.textContent = 'in progress';
      else if (state === 'done') stateEl.textContent = 'done';
      else if (state === 'error') stateEl.textContent = 'error';
      else if (state === 'skipped') stateEl.textContent = 'skipped';
      else stateEl.textContent = 'waiting';
    }

    if (timeEl) timeEl.textContent = ms === null ? '—' : formatDuration(ms, { empty: '—' });
  }

  /** Reset pipeline and feed to initial idle state. */
  reset(): void {
    this.setSummary('waiting');
    for (const step of this.stepOrder) this.setStep(step, 'pending', null);
    this.els.log.innerHTML = '<div class="progressEmpty">No activity yet.</div>';
  }

  /** Apply server-provided timing payload to the pipeline UI. */
  applyTimingMs(timing: any): void {
    const data = timing && typeof timing === 'object' ? timing : {};
    let any = false;
    const missing: string[] = [];

    for (const step of this.stepOrder) {
      const ms = getTimingMs(data, `${step}_ms`);
      if (ms === null) {
        missing.push(step);
        continue;
      }
      any = true;
      this.setStep(step, 'done', ms);
    }

    const total = getTimingMs(data, 'total_ms');
    if (any || total !== null) {
      for (const step of missing) this.setStep(step, 'skipped', null);
    } else {
      for (const step of missing) this.setStep(step, 'pending', null);
    }

    if (total !== null) {
      this.setSummary(`total ${formatDuration(total)}`, 'ok');
      return;
    }
    if (any) {
      this.setSummary('timings recorded');
      return;
    }
    this.setSummary('waiting');
  }

  /** Append one line to the live progress feed. */
  append(line: string): void {
    let feed = this.els.log.querySelector('.progressFeed') as HTMLElement | null;
    if (!feed) {
      this.els.log.innerHTML = '';
      feed = document.createElement('div');
      feed.className = 'progressFeed';
      this.els.log.appendChild(feed);
    }

    const row = document.createElement('div');
    row.className = 'progressItem';

    const ts = document.createElement('div');
    ts.className = 'progressTs';
    ts.textContent = new Date().toLocaleTimeString();

    const msg = document.createElement('div');
    msg.className = 'progressMsg';
    msg.textContent = String(line || '');

    row.appendChild(ts);
    row.appendChild(msg);
    feed.appendChild(row);

    this.els.log.scrollTop = this.els.log.scrollHeight;
  }
}
