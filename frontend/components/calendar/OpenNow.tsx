import { Button } from "@/components/ui/button";
import { ChevronDown } from "lucide-react";
import { DEADLINE_TONE_SURFACE, DEADLINE_TONE_TEXT, deadlineTone } from "@/lib/deadlineTone";
import { daysUntilDeadline, itemDate, registrationEvents, selectOpenNow, shortDate } from "@/lib/hiringCalendar";
import type { CalendarItem } from "@/lib/hiringCalendar";
import { CALENDAR_FOCUS, HowToApply, OfficialLink } from "./CalendarItem";

export default function OpenNow({ items, today, onSelect }: { items: CalendarItem[]; today: string; onSelect: (item: CalendarItem) => void }) {
  const open = selectOpenNow(items, today);
  if (!open.length) return null;
  return <section aria-labelledby="calendar-open-heading" className="rounded-xl border border-success/25 bg-emerald-50 p-3 sm:p-4">
    <h2 id="calendar-open-heading" className="text-sm font-semibold text-success"><span aria-hidden="true">● </span>Open now — apply before it closes</h2>
    <div className={`mt-3 flex max-h-[45dvh] max-w-full gap-3 overflow-auto pb-2 ${CALENDAR_FOCUS}`} tabIndex={0} role="region" aria-label="Open registration windows">
      {open.map((item) => {
        const days = daysUntilDeadline(item, today);
        // deadlineTone uses local wall-clock days. Supply IST day labels to keep the tone consistent worldwide.
        const tone = days !== null && item.edition.closes_at
          ? deadlineTone(`${itemDate(item.edition.closes_at)}T12:00:00`, new Date(`${today}T12:00:00`)) : null;
        const closing = registrationEvents(item).find((event) => event.kind === "closes");
        const deadline = days !== null && item.edition.closes_at
          ? `Closes ${shortDate(itemDate(item.edition.closes_at))} · ${days === 0 ? "closes today" : `${days} ${days === 1 ? "day" : "days"} left`}`
          : item.metadata.deadline_rolling ? "Deadline rolling · apply early" : closing ? `Closes ${closing.label} · ${item.edition.basis}` : "Check the current call for its deadline";
        return <article key={item.id} className={`flex w-72 max-w-full shrink-0 flex-col rounded-lg border p-3 ${tone ? DEADLINE_TONE_SURFACE[tone] : "border-success/20 bg-card"}`}>
          <button type="button" className={`min-h-11 break-words text-left text-sm font-semibold leading-5 hover:text-primary ${CALENDAR_FOCUS}`} onClick={() => onSelect(item)}>{item.programme.name}</button>
          <p className="mt-1 text-xs text-muted-foreground">{item.programme.organiser}</p>
          <p className={`my-3 text-xs font-medium ${tone ? DEADLINE_TONE_TEXT[tone] : "text-success"}`}>{deadline}</p>
          <div className="mt-auto flex flex-wrap items-center gap-2"><OfficialLink item={item} /><Button variant="ghost" className="min-h-11 px-2 text-xs" onClick={() => onSelect(item)}>Details</Button></div>
          <details className="mt-1 text-xs">
            <summary className={`flex min-h-11 cursor-pointer items-center justify-between rounded font-medium ${CALENDAR_FOCUS}`}>How to apply<ChevronDown className="size-4" aria-hidden="true" /></summary>
            <HowToApply item={item} />
          </details>
        </article>;
      })}
    </div>
  </section>;
}
