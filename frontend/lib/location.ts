export function summarizeLocation(
  raw: string | null | undefined,
  maxChars = 40,
): { short: string | null; hiddenCount: number; full: string | null } {
  const full = raw?.replace(/\s+/g, " ").trim() || null;
  if (!full) return { short: null, hiddenCount: 0, full: null };
  if (full.length <= maxChars) return { short: full, hiddenCount: 0, full };

  const segments = full.split(/[,;]/).map((segment) => segment.trim()).filter(Boolean);
  const first = segments[0] ?? full;
  if (first.length > maxChars) {
    return {
      short: `${first.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`,
      hiddenCount: Math.max(0, segments.length - 1),
      full,
    };
  }

  let short = first;
  let kept = 1;
  for (const segment of segments.slice(1)) {
    const next = `${short}, ${segment}`;
    if (next.length > maxChars) break;
    short = next;
    kept += 1;
  }

  return { short, hiddenCount: segments.length - kept, full };
}

export function isSinglePlace(raw: string | null | undefined): boolean {
  return (raw?.split(/[,;]/).length ?? 0) <= 3;
}
