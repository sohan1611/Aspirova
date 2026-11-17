import Link from "next/link";
import { formatDateUtc } from "@/lib/date";
import { closingSoonItems, calendarPreviewItems } from "@/lib/home";
import { windowText, type CalendarItem } from "@/lib/hiringCalendar";
import type { OpportunityListItem } from "@/lib/types";

const linkClass = "inline-flex min-h-11 items-center text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export default function HomePreviews({ closing, calendar, asOf }: {
  closing: OpportunityListItem[] | null; calendar: CalendarItem[] | null; asOf: number;
}) {
  const roles = closingSoonItems(closing ?? [], asOf);
  const windows = calendarPreviewItems(calendar ?? [], asOf);
  return (
    <div className="min-w-0 space-y-4">
      <section aria-labelledby="home-closing-title" className="rounded-lg border border-border bg-card p-4">
        <h2 id="home-closing-title" className="font-serif text-xl font-bold">Closing soon</h2>
        <p className="mt-1 text-xs text-muted-foreground">Explicit deadlines from the source. Check before applying.</p>
        {roles.length ? <ol className="mt-2 grid gap-x-4 sm:grid-cols-2">
          {roles.map(item => <li key={item.slug} className="min-w-0 border-t border-border py-1">
            <Link href={`/opportunity/${item.slug}`} className={`${linkClass} max-w-full break-words`}>{item.title}</Link>
            <p className="text-xs text-muted-foreground">{item.company?.name} · Deadline <time dateTime={item.deadline!}>{formatDateUtc(item.deadline!)}</time></p>
          </li>)}
        </ol> : <p className="mt-3 text-sm text-muted-foreground">{closing === null ? "Closing deadlines are temporarily unavailable." : "No upcoming explicit deadlines right now."} <Link href="/internships" className={linkClass}>Browse internships</Link></p>}
      </section>
      <section aria-labelledby="home-calendar-title" className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-x-3">
          <h2 id="home-calendar-title" className="font-serif text-xl font-bold">Hiring Calendar</h2>
          <Link href="/calendar" className={linkClass}>Open calendar →</Link>
        </div>
        <p className="text-xs text-muted-foreground">Next windows · official dates first, tentative trends labelled.</p>
        {windows.length ? <ol className="mt-2 divide-y divide-border">
          {windows.map(item => <li key={item.id} className="py-1">
            <Link href={`/calendar?item=${encodeURIComponent(item.id)}`} className={linkClass}>{item.programme.name}</Link>
            <p className="text-xs leading-5 text-muted-foreground"><span className="font-medium">{item.edition.basis === "official" ? "Official" : "Tentative · historical trend"}</span> · {windowText(item)}</p>
          </li>)}
        </ol> : <p className="mt-3 text-sm text-muted-foreground">{calendar === null ? "Calendar preview is temporarily unavailable." : "No dated windows in the next 12 months."} <Link href="/calendar" className={linkClass}>Explore the calendar</Link></p>}
      </section>
    </div>
  );
}
