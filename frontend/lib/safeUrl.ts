/**
 * Returns `value` only when it is an absolute http(s) link with a host (SEC-03).
 *
 * Crawled and curated links end up in `href` attributes. React 19 already
 * blocks `javascript:` URLs, but `data:`, `vbscript:`, relative and malformed
 * values would still render as clickable links. The trimmed original string is
 * returned, not a re-serialised URL, so tracking parameters and encoding stay
 * exactly as the source gave them.
 */
export function safeExternalUrl(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    const url = new URL(trimmed);
    const webProtocol = url.protocol === "http:" || url.protocol === "https:";
    return webProtocol && url.hostname ? trimmed : null;
  } catch {
    return null;
  }
}
