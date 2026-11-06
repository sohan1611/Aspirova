export type DeadlineTone = "imminent" | "near" | "far";

export function deadlineTone(deadlineIso: string, now: Date): DeadlineTone | null {
  const deadline = new Date(deadlineIso);
  if (!Number.isFinite(deadline.getTime()) || !Number.isFinite(now.getTime())) {
    return null;
  }

  // Map local calendar dates to UTC day numbers so DST cannot change the gap.
  const days = (
    Date.UTC(deadline.getFullYear(), deadline.getMonth(), deadline.getDate()) -
    Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  ) / 86_400_000;
  if (days < 0) return null;
  if (days <= 1) return "imminent";
  if (days <= 7) return "near";
  return "far";
}

export const DEADLINE_TONE_TEXT = {
  imminent: "text-red-700",
  near: "text-amber-700",
  far: "text-emerald-700",
} as const;

export const DEADLINE_TONE_SURFACE = {
  imminent: "bg-red-50 border-red-200",
  near: "bg-amber-50 border-amber-200",
  far: "bg-emerald-50 border-emerald-200",
} as const;

// Local wall-clock timestamps keep these runnable in any visitor time zone.
export const DEADLINE_TONE_EXAMPLES = [
  { label: "today", deadlineIso: "2026-11-06T18:00:00", now: "2026-11-06T12:00:00", expected: "imminent" },
  { label: "tomorrow", deadlineIso: "2026-11-07T18:00:00", now: "2026-11-06T12:00:00", expected: "imminent" },
  { label: "2 days", deadlineIso: "2026-11-08T18:00:00", now: "2026-11-06T12:00:00", expected: "near" },
  { label: "7 days", deadlineIso: "2026-11-13T18:00:00", now: "2026-11-06T12:00:00", expected: "near" },
  { label: "8 days", deadlineIso: "2026-11-14T18:00:00", now: "2026-11-06T12:00:00", expected: "far" },
  { label: "yesterday", deadlineIso: "2026-11-05T18:00:00", now: "2026-11-06T12:00:00", expected: null },
] as const;
