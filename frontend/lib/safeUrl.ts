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
  if (!trimmed || /[\s\\\x00-\x1f\x7f]/.test(trimmed) || /^[^:]+:\/\/[^/?#]*@/.test(trimmed)) return null;
  try {
    const url = new URL(trimmed);
    const webProtocol = url.protocol === "http:" || url.protocol === "https:";
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    if (!webProtocol || !host || url.username || url.password || url.port === "0") return null;
    if (["localhost", "local", "internal", "home.arpa"].some(suffix => host === suffix || host.endsWith(`.${suffix}`))) return null;
    if (host.startsWith("[")) {
      // Public unicast IPv6 only; excludes loopback, mapped IPv4 and link-local.
      if (!/^\[[23][0-9a-f]{3}:/.test(host) || host.startsWith("[2001:db8:")) return null;
    } else if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      const [a, b] = host.split(".").map(Number);
      if (a === 0 || a === 10 || a === 127 || a >= 224 || (a === 100 && b >= 64 && b <= 127)
        || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31)
        || (a === 192 && (b === 0 || b === 168)) || (a === 198 && (b === 18 || b === 19))) return null;
    } else if (!host.includes(".") || !host.split(".").every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
    return trimmed;
  } catch {
    return null;
  }
}
