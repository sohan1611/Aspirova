"use client";

import { useDeferredValue } from "react";
import { isListingClosed } from "@/lib/deadline";
import { deadlineTone, DEADLINE_TONE_SURFACE, DEADLINE_TONE_TEXT } from "@/lib/deadlineTone";
import { useHydrated } from "@/lib/useHydrated";

interface RelativeDeadlineProps {
  deadline: string | null;
  closedAt: string | null;
  category: string | null;
  absoluteText: string | null;
  closedText: string;
  estimated: boolean;
  banner?: boolean;
}

function relativeText(deadline: string, now: Date, banner: boolean): string {
  const date = new Date(deadline);
  const days = (
    Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) -
    Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  ) / 86_400_000;
  if (days === 0) {
    return banner ? "Closes today" : "Due today";
  }
  if (days === 1) return banner ? "Closes tomorrow" : "Due tomorrow";
  return banner ? `Closing in ${days} days` : `Due in ${days} days`;
}

export default function RelativeDeadline({
  deadline,
  closedAt,
  category,
  absoluteText,
  closedText,
  estimated,
  banner = false,
}: RelativeDeadlineProps) {
  // Deferred: the switch to relative text renders as a low-priority, yielding
  // update instead of joining the hydration task, which kept a long task
  // on phones across twenty cards.
  const hydrated = useDeferredValue(useHydrated(), false);
  // Keep text, icons, and styling stable until hydration has completed.
  const closed = hydrated ? isListingClosed(closedAt, deadline, category) : !!closedAt;
  const now = hydrated ? new Date() : null;
  const tone = now && !closed && deadline ? deadlineTone(deadline, now) : null;
  const relative = now && deadline && (tone === "imminent" || tone === "near")
    ? relativeText(deadline, now, banner)
    : null;
  let text = absoluteText;
  let icon = "ico-calendar";
  if (closed) {
    text = closedText;
    icon = "ico-clock";
  } else if (relative) {
    text = `${relative}${estimated ? " (estimated)" : ""}`;
    icon = "ico-clock";
  } else if (banner && tone === "far") {
    text = "Registering now";
    icon = "ico-check-circle";
  }

  const className = banner
    ? `absolute right-3 top-3 inline-flex max-w-[calc(100%-1.5rem)] items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold shadow-soft ${tone ? `${DEADLINE_TONE_SURFACE[tone]} ${DEADLINE_TONE_TEXT[tone]}` : "border-border bg-card text-muted-foreground"}`
    : `tnum inline-flex items-center gap-1.5 text-xs ${tone ? `font-medium ${DEADLINE_TONE_TEXT[tone]}` : "text-muted-foreground"}`;

  return (
    <span className={className} title={absoluteText ?? undefined} data-tone={tone ?? "none"} data-deadline={deadline ?? undefined}>
      <span aria-hidden="true" className={`ico ${icon} size-3.5`} />
      {text}
    </span>
  );
}
