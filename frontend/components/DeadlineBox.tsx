"use client";

import { useDeferredValue, type ReactNode } from "react";
import { deadlineTone, DEADLINE_TONE_SURFACE, DEADLINE_TONE_TEXT } from "@/lib/deadlineTone";
import { useHydrated } from "@/lib/useHydrated";

export default function DeadlineBox({
  deadlineIso,
  closed,
  children,
}: {
  deadlineIso: string;
  closed: boolean;
  children: ReactNode;
}) {
  const hydrated = useDeferredValue(useHydrated(), false);
  const tone = hydrated && !closed ? deadlineTone(deadlineIso, new Date()) : null;
  const colours = closed
    ? "border-border bg-secondary/50 text-muted-foreground"
    : tone
      ? `${DEADLINE_TONE_SURFACE[tone]} ${DEADLINE_TONE_TEXT[tone]}`
      : "border-border bg-secondary/50 text-foreground";

  return (
    <div
      className={`inline-flex max-w-full items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium ${colours}`}
      data-tone={tone ?? "none"}
      data-deadline={deadlineIso}
    >
      {children}
    </div>
  );
}
