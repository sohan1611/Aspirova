import { dateLabel, keyDatesText, registrationMonths } from "@/lib/hiringCalendar";
import type { CalendarItem, RecurringRow } from "@/lib/hiringCalendar";
import { ItemRow } from "./CalendarItem";

export function RecurringSection({ rows, onSelect }: { rows: RecurringRow[]; onSelect: (item: CalendarItem) => void }) {
  if (!rows.length) return null;
  return <section aria-labelledby="calendar-recurring-heading" className="space-y-3">
    <h2 id="calendar-recurring-heading" className="font-serif text-xl font-semibold">Every month / recurring <span className="font-sans text-sm font-normal text-muted-foreground">({rows.length})</span></h2>
    {rows.map(({ item, rule }) => <ItemRow key={item.programme.slug} item={item} dateChip="↻" text={rule} onSelect={onSelect} />)}
  </section>;
}

export function AnytimeSection({ items, onSelect }: { items: CalendarItem[]; onSelect: (item: CalendarItem) => void }) {
  if (!items.length) return null;
  return <section aria-labelledby="calendar-anytime-heading" className="space-y-3">
    <h2 id="calendar-anytime-heading" className="font-serif text-xl font-semibold">Apply anytime <span className="font-sans text-sm font-normal text-muted-foreground">({items.length})</span></h2>
    <p className="text-sm text-muted-foreground">Rolling and undated routes. Check the current vacancy, institution or lab notice for availability.</p>
    {items.map((item) => <ItemRow key={item.id} item={item} text={item.metadata.deadline_rolling ? keyDatesText(item) : item.metadata.opening_text ?? "Registration timing varies. See details and the official notice."} onSelect={onSelect} />)}
  </section>;
}

export default function MonthList({ items, recurring, range, onSelect }: {
  items: CalendarItem[]; recurring: RecurringRow[]; range: { from: string; to: string }; onSelect: (item: CalendarItem) => void;
}) {
  const groups = registrationMonths(items, range);
  const listed = new Set(groups.flatMap(({ rows }) => rows.map(({ item }) => item.id)));
  const continuing = items.filter((item) => !listed.has(item.id));
  return <div className="space-y-7">
    <RecurringSection rows={recurring} onSelect={onSelect} />
    {groups.map(({ month, rows }) => <section key={month} className="space-y-3" aria-label={dateLabel(`${month}-01T12:00:00Z`, "month")}>
      <h2 className="flex items-center gap-2 font-serif text-xl font-semibold">{dateLabel(`${month}-01T12:00:00Z`, "month")}<span className="font-sans text-xs font-normal text-muted-foreground">{rows.length ? `${rows.length} ${rows.length === 1 ? "programme" : "programmes"}` : ""}</span></h2>
      {rows.length ? rows.map(({ item, events }) => <ItemRow key={item.id} item={item} dateChip={(events.find((event) => event.kind === "closes") ?? events[0]).label} text={keyDatesText(item, events)} onSelect={onSelect} />)
        : <p className="border-l-2 border-border pl-3 text-xs text-muted-foreground">No registration openings or deadlines listed.</p>}
    </section>)}
    {!!continuing.length && <section className="space-y-3" aria-label="Continuing registration windows"><h2 className="font-serif text-xl font-semibold">Continuing registration windows</h2>{continuing.map((item) => <ItemRow key={item.id} item={item} onSelect={onSelect} />)}</section>}
  </div>;
}
