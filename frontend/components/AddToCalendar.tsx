"use client";

import { buildIcs, googleCalendarUrl, type DeadlineEvent } from "@/lib/calendar";

export default function AddToCalendar({ event }: { event: DeadlineEvent }) {
  function download() {
    const blob = new Blob([buildIcs(event)], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${event.slug}-deadline.ics`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
      <span>Add to calendar:</span>
      <a href={googleCalendarUrl(event)} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4 hover:text-foreground">
        Google Calendar
      </a>
      <button type="button" onClick={download} className="underline underline-offset-4 hover:text-foreground">
        Download .ics
      </button>
    </div>
  );
}
