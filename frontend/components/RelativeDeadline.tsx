"use client";

import { CalendarDays, CheckCircle2, Clock } from "lucide-react";
import { isListingClosed } from "@/lib/deadline";
import { useHydrated } from "@/lib/useHydrated";

const DAY_IN_MS = 24 * 60 * 60 * 1000;

interface RelativeDeadlineProps {
  deadline: string | null;
  closedAt: string | null;
  category: string | null;
  absoluteText: string | null;
  closedText: string;
  estimated: boolean;
  banner?: boolean;
}

function relativeText(deadline: string, banner: boolean): string | null {
  const now = new Date();
  const date = new Date(deadline);
  const remaining = date.getTime() - now.getTime();
  if (remaining < 0 || !Number.isFinite(remaining) || remaining > 7 * DAY_IN_MS) {
    return null;
  }

  if (date.toDateString() === now.toDateString()) {
    return banner ? "Closes today" : "Due today";
  }

  const days = Math.ceil(remaining / DAY_IN_MS);
  const duration = `${days} ${days === 1 ? "day" : "days"}`;
  return banner ? `Closing in ${duration}` : `Due in ${duration}`;
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
  const hydrated = useHydrated();
  // Keep text, icons, and styling stable until hydration has completed.
  const closed = hydrated ? isListingClosed(closedAt, deadline, category) : !!closedAt;
  const relative = hydrated && !closed && deadline ? relativeText(deadline, banner) : null;
  let text = absoluteText;
  let Icon = CalendarDays;
  if (closed) {
    text = closedText;
    Icon = Clock;
  } else if (relative) {
    text = `${relative}${estimated ? " (estimated)" : ""}`;
    Icon = Clock;
  } else if (hydrated && banner && deadline) {
    text = "Registering now";
    Icon = CheckCircle2;
  }

  const className = banner
    ? `absolute right-3 top-3 inline-flex max-w-[calc(100%-1.5rem)] items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-xs font-semibold shadow-soft ${closed ? "border-border text-muted-foreground" : relative ? "border-amber-200 text-amber-700" : "border-emerald-200 text-success"}`
    : `tnum inline-flex items-center gap-1.5 text-xs ${relative ? "font-medium text-amber-700" : "text-muted-foreground"}`;

  return (
    <span className={className} title={absoluteText ?? undefined}>
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      {text}
    </span>
  );
}
