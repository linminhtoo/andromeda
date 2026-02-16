/** Format a duration in milliseconds into a compact human-readable string. */
export function formatDuration(ms: unknown, { empty = '' }: { empty?: string } = {}): string {
  if (ms === null || ms === undefined) return empty;
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return empty;
  if (n < 1000) return `${Math.round(n)}ms`;
  const s = n / 1000;
  if (s < 10) return `${s.toFixed(2)}s`;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = s - m * 60;
  return `${m}m${rs.toFixed(0)}s`;
}

/** Render an ISO-like timestamp value using the browser locale. */
export function fmtDate(iso: unknown): string {
  if (!iso) return 'unknown time';
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString();
}
