export interface FreshnessData {
  last_verified_at?: string | null;
  freshness?: "fresh" | "stale" | null;
  freshness_reason?: "age" | "verification" | null;
  stale_after_hours?: number | null;
}

export function freshnessText(value: FreshnessData, now?: number): string | null {
  const verified = value.last_verified_at ? Date.parse(value.last_verified_at) : NaN;
  const hours = value.stale_after_hours;
  const stale = value.freshness === "stale" || (
    now !== undefined && Number.isFinite(verified) && typeof hours === "number" && hours > 0
    && now - verified > hours * 3_600_000
  );
  if (stale) return value.freshness_reason === "age" ? "Old posting — check source" : "Not verified recently";
  if (!Number.isFinite(verified)) return null;
  if (now === undefined) return `Verified ${new Date(verified).toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  })}`;
  const days = Math.max(0, Math.floor((now - verified) / 86_400_000));
  return days === 0 ? "Verified today" : `Verified ${days} ${days === 1 ? "day" : "days"} ago`;
}

export function relativeFreshnessText(value: FreshnessData): string | null {
  return freshnessText(value, Date.now());
}
