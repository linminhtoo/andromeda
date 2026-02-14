/** Escape HTML-sensitive characters in free-form text. */
export function safeText(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** Escape HTML-sensitive characters for use inside quoted HTML attributes. */
export function escapeHtmlAttr(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Allow only safe outbound href values used by renderer links. */
export function sanitizeHref(href: unknown): string {
  const value = String(href ?? '').trim();
  if (!value) return '#';
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/')) return value;
  return '#';
}
