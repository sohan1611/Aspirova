import { categoryColour, categoryLabel, dateLabel, itemDate, keyDatesText, monthRange, monthsInRange, timelineWindow } from "@/lib/hiringCalendar";
import type { CalendarItem, RecurringRow } from "@/lib/hiringCalendar";
import { CALENDAR_FOCUS, StatusBadge } from "./CalendarItem";

export default function Timeline({ items, recurring, range, today, onSelect }: {
  items: CalendarItem[]; recurring: RecurringRow[]; range: { from: string; to: string }; today: string; onSelect: (item: CalendarItem) => void;
}) {
  const months = monthsInRange(range);
  const rows = [
    ...items.map((item) => ({ item, occurrences: [item], rule: "" })),
    ...recurring,
  ];
  const categories = [...new Set(rows.map(({ item }) => item.programme.category))];
  const columns = { gridTemplateColumns: `repeat(${months.length}, minmax(0, 1fr))` };
  const todayMonth = months.indexOf(today.slice(0, 7));
  const todayPosition = todayMonth < 0 ? null : ((todayMonth + (Number(today.slice(8)) - 0.5) / Number(monthRange(today.slice(0, 7)).to.slice(8))) / months.length) * 100;
  function todayLine() {
    return todayPosition !== null && <span className="pointer-events-none absolute inset-y-0 z-10 border-l-2 border-primary/70" style={{ left: `${todayPosition}%` }} aria-hidden="true" />;
  }

  return <section aria-label="Registration timeline" className="min-w-0 space-y-3">
    <p id="calendar-timeline-legend" className="text-xs leading-5 text-muted-foreground">Solid bars show official windows. Dashed bars show tentative windows. ◆ marks an official deadline. Fading bars have a rolling deadline.</p>
    <p className="text-xs text-muted-foreground sm:hidden">Scroll across the timeline to see every month →</p>
    <div className={`max-w-full overflow-x-auto rounded-lg border border-border bg-card ${CALENDAR_FOCUS}`} role="region" tabIndex={0} aria-label="Timeline, scroll horizontally for all months" aria-describedby="calendar-timeline-legend">
      <div role="table" aria-label="Registration windows by category and month" aria-colcount={months.length + 1} style={{ minWidth: `${180 + months.length * 90}px` }}>
        <div role="row" className="grid grid-cols-[180px_minmax(0,1fr)] border-b border-border">
          <div role="columnheader" className="sticky left-0 z-20 flex items-center bg-card px-3 text-xs font-semibold">Programme</div>
          <div role="presentation" className="relative grid" style={columns}>
            {months.map((month) => <div role="columnheader" key={month} className={`border-l border-border py-4 text-center text-xs ${month === today.slice(0, 7) ? "bg-accent font-semibold text-primary" : "text-muted-foreground"}`} aria-current={month === today.slice(0, 7) ? "date" : undefined}>{dateLabel(`${month}-01T12:00:00Z`, "month")}</div>)}
            {todayLine()}
          </div>
        </div>
        {categories.map((category) => {
          const categoryRows = rows.filter(({ item }) => item.programme.category === category);
          return <div role="rowgroup" key={category}>
            <div role="row" className="bg-secondary/60">
              <div role="cell" aria-colspan={months.length + 1} className="py-2">
                <span className="sticky left-0 inline-flex min-h-8 max-w-[30rem] items-center gap-2 bg-secondary px-3 text-xs font-semibold">
                  <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: categoryColour(category) }} aria-hidden="true" />
                  {categoryLabel(category, categoryRows[0].item.programme.category_label)} ({categoryRows.length})
                </span>
              </div>
            </div>
            {categoryRows.map(({ item, occurrences, rule }) => <div key={item.id} role="row" className="grid grid-cols-[180px_minmax(0,1fr)] border-b border-border last:border-b-0">
              <div role="rowheader" className="sticky left-0 z-20 min-w-0 border-r border-border bg-card p-2">
                <button type="button" onClick={() => onSelect(item)} className={`block min-h-11 w-full break-words px-1 text-left text-xs font-semibold leading-5 hover:text-primary ${CALENDAR_FOCUS}`}>{item.programme.name}</button>
                <div className="mt-1 px-1"><StatusBadge item={item} /></div>
              </div>
              <div role="cell" aria-colspan={months.length} aria-colindex={2} className="relative grid items-center py-3" style={columns}>
                <span className="sr-only">{rule || keyDatesText(item)}</span>
                <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid" style={columns}>{months.map((month) => <span key={month} className="border-l border-border/60" />)}</div>
                {occurrences.map((occurrence) => {
                  const span = timelineWindow(occurrence, months);
                  if (!span) return null;
                  const colour = categoryColour(category);
                  const tentative = occurrence.edition.basis === "tentative";
                  const closed = occurrence.edition.status === "closed";
                  const marker = span.deadline !== null && span.deadline >= 0;
                  const deadlineOnly = !occurrence.edition.opens_at && marker;
                  const markerDay = occurrence.edition.closes_at ? itemDate(occurrence.edition.closes_at) : null;
                  const markerPosition = marker && markerDay
                    ? ((span.deadline! - span.start + Number(markerDay.slice(8)) / Number(monthRange(markerDay.slice(0, 7)).to.slice(8))) / (span.end - span.start + 1)) * 100 : 0;
                  return <button key={occurrence.id} type="button" onClick={() => onSelect(occurrence)} aria-label={`${occurrence.programme.name}, ${keyDatesText(occurrence)}`}
                    style={{
                      gridColumn: `${span.start + 1} / ${span.end + 2}`, gridRow: 1,
                      borderColor: deadlineOnly ? "transparent" : closed || tentative ? "var(--border)" : occurrence.is_open_now ? "var(--color-success)" : "var(--primary)",
                      background: deadlineOnly ? "transparent" : span.rolling ? `linear-gradient(to right, color-mix(in srgb, ${colour} 18%, white), transparent)` : closed ? "var(--muted)" : `color-mix(in srgb, ${colour} ${tentative ? "7" : "18"}%, white)`,
                      borderRightStyle: span.rolling ? "none" : undefined,
                    }}
                    className={`relative z-10 mx-0.5 flex min-h-11 min-w-0 items-center rounded-md border px-2 text-left text-xs ${tentative ? "border-dashed text-muted-foreground" : closed ? "text-muted-foreground" : "text-foreground"} ${CALENDAR_FOCUS}`}>
                    <span className={deadlineOnly ? "sr-only" : "truncate"}>{deadlineOnly ? "Deadline" : span.rolling ? "Rolling · apply early" : tentative ? "Tentative" : occurrence.is_open_now ? "Open now" : "Registration"}</span>
                    {marker && <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm" style={{ left: `${Math.min(97, markerPosition)}%`, color: closed ? "var(--muted-foreground)" : colour }} aria-hidden="true">◆</span>}
                  </button>;
                })}
                {todayLine()}
              </div>
            </div>)}
          </div>;
        })}
      </div>
    </div>
    {todayPosition !== null && <p className="text-xs text-primary">The blue line marks today, {dateLabel(`${today}T12:00:00Z`)}.</p>}
  </section>;
}
