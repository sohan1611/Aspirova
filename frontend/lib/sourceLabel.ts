const SOURCE_HOSTS: { match: string; label: string }[] = [
  { match: "greenhouse.io", label: "Greenhouse" },
  { match: "lever.co", label: "Lever" },
  { match: "ashbyhq.com", label: "Ashby" },
  { match: "remoteok.com", label: "RemoteOK" },
];

/**
 * Derives an honest fallback "via X" label from the apply_url's own host -
 * the same domain the user lands on when they click Apply. Returns null for
 * anything unrecognized rather than guessing.
 */
export function getSourceLabel(applyUrl: string): string | null {
  try {
    const host = new URL(applyUrl).hostname;
    return SOURCE_HOSTS.find((s) => host.endsWith(s.match))?.label ?? null;
  } catch {
    return null;
  }
}
