"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { addDays, calendarDays, categoryColour, dateLabel, monthPrecisionItems, registrationEvents, shiftMonth } from "@/lib/hiringCalendar";
import type { CalendarItem } from "@/lib/hiringCalendar";
import { ItemRow, statusClass } from "./CalendarItem";

export default function MonthGrid({ items, range, today, onSelect, onOutsideMonth }: {
  items: CalendarItem[]; range: { from: string; to: string }; today: string;
  onSelect: (item: CalendarItem) => void; onOutsideMonth: (month: string) => void;
}) {
  const [month, setMonth] = useState(today >= range.from && today <= range.to ? today.slice(0, 7) : range.from.slice(0, 7));
  const [selectedDay, setSelectedDay] = useState("");
  const [focusDay, setFocusDay] = useState(today >= range.from && today <= range.to && today.startsWith(month) ? today : range.from);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const pendingFocus = useRef(false);
  const cells = calendarDays(month);
  const monthItems = monthPrecisionItems(items, month);
  const entries = useMemo(() => items.flatMap(registrationEvents).filter((event) => event.precision === "day"), [items]);
  const dayEvents = entries.filter((event) => event.from === selectedDay);

  useEffect(() => {
    if (pendingFocus.current) { buttons.current.get(focusDay)?.focus(); pendingFocus.current = false; }
  }, [focusDay, month]);

  function navigate(next: string) {
    setSelectedDay("");
    if (next < range.from.slice(0, 7) || next > range.to.slice(0, 7)) { onOutsideMonth(next); return; }
    setMonth(next);
    setFocusDay(`${next}-01` < range.from ? range.from : `${next}-01`);
  }

  function onKey(event: KeyboardEvent<HTMLButtonElement>, day: string) {
    const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key];
    const weekday = (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
    let target = offset ? addDays(day, offset) : event.key === "Home" ? addDays(day, -weekday) : event.key === "End" ? addDays(day, 6 - weekday) : null;
    if (event.key === "PageUp" || event.key === "PageDown") target = `${shiftMonth(day.slice(0, 7), event.key === "PageUp" ? -1 : 1)}-01`;
    if (!target) return;
    event.preventDefault();
    if (target < range.from || target > range.to) { onOutsideMonth(target.slice(0, 7)); return; }
    pendingFocus.current = true;
    setMonth(target.slice(0, 7));
    setFocusDay(target);
  }

  return <section className="min-w-0 space-y-4" aria-label="Month calendar">
    <div className="flex items-center justify-between gap-2">
      <Button variant="outline" className="min-h-11 min-w-11" aria-label="Previous calendar month" onClick={() => navigate(shiftMonth(month, -1))}>‹</Button>
      <h2 className="text-center font-serif text-xl font-semibold" aria-live="polite">{dateLabel(`${month}-01T12:00:00Z`, "month")}</h2>
      <Button variant="outline" className="min-h-11 min-w-11" aria-label="Next calendar month" onClick={() => navigate(shiftMonth(month, 1))}>›</Button>
    </div>
    <div role="grid" aria-label={dateLabel(`${month}-01T12:00:00Z`, "month")} className="overflow-hidden rounded-lg border border-border bg-card">
      <div role="row" className="grid grid-cols-7 border-b border-border bg-secondary/50">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <span key={day} role="columnheader" className="py-3 text-center text-xs text-muted-foreground">{day}</span>)}
      </div>
      {Array.from({ length: cells.length / 7 }, (_, week) => <div role="row" key={week} className="grid grid-cols-7">
        {cells.slice(week * 7, week * 7 + 7).map((day, index) => {
          if (!day) return <div key={`empty-${index}`} role="gridcell" className="border-r border-b border-border/60 bg-muted/20 last:border-r-0" />;
          const events = entries.filter((event) => event.from === day);
          const outside = day < range.from || day > range.to;
          return <div key={day} role="gridcell" aria-selected={selectedDay === day} className="min-w-0 border-r border-b border-border/60 last:border-r-0">
            <button type="button" ref={(node) => { if (node) buttons.current.set(day, node); else buttons.current.delete(day); }}
              tabIndex={focusDay === day ? 0 : -1} disabled={outside} aria-current={day === today ? "date" : undefined}
              aria-label={`${dateLabel(`${day}T12:00:00Z`)}, ${events.length ? events.map((entry) => `${entry.item.programme.name} ${entry.kind}`).join(", ") : "no registration dates"}`}
              aria-expanded={selectedDay === day} onKeyDown={(event) => onKey(event, day)} onFocus={() => setFocusDay(day)} onClick={() => setSelectedDay(day)}
              className={`flex min-h-28 w-full min-w-0 flex-col items-stretch gap-1 p-0.5 text-left hover:bg-accent/40 focus-visible:relative focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-35 sm:min-h-36 sm:p-2 ${selectedDay === day ? "bg-accent" : ""}`}>
              <span className={`mb-1 inline-flex size-7 items-center justify-center self-start rounded-full text-xs ${day === today ? "bg-primary font-bold text-primary-foreground" : "text-muted-foreground"}`}>{Number(day.slice(8))}</span>
              {events.slice(0, 2).map(({ item, kind }) => <span key={`${item.id}-${kind}`} style={{ borderLeftColor: categoryColour(item.programme.category) }}
                className={`block min-w-0 rounded border-l-2 px-0.5 py-1 text-[10px] leading-3 sm:px-1 sm:text-xs ${statusClass(item)}`}>
                <span className="line-clamp-2 break-words">{item.programme.organiser || item.programme.name} · {kind}</span>
              </span>)}
              {events.length > 2 && <span className="px-0.5 text-[10px] font-medium text-primary sm:text-xs">+{events.length - 2} more</span>}
            </button>
          </div>;
        })}
      </div>)}
    </div>
    <p className="sr-only">Use arrow keys to move between dates, Home and End for the week, and Page Up or Page Down for another month. Press Enter to show a day’s items.</p>
    {selectedDay && <section className="space-y-3 rounded-lg bg-secondary/40 p-3" aria-label="Selected day registration dates" aria-live="polite">
      <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">{dateLabel(`${selectedDay}T12:00:00Z`)}</h3><Button variant="ghost" className="min-h-11" onClick={() => { setSelectedDay(""); buttons.current.get(selectedDay)?.focus(); }}>Close day</Button></div>
      {dayEvents.length ? dayEvents.map(({ item, kind, label }) => <ItemRow key={`${item.id}-${kind}`} item={item} text={`Registration ${kind} ${label} · ${item.edition.basis}`} onSelect={onSelect} />) : <p className="text-sm text-muted-foreground">No registration openings or deadlines on this day.</p>}
    </section>}
    {monthItems.length > 0 && <section aria-label="Month-precision registration windows" className="space-y-3">
      <h3 className="font-serif text-lg font-semibold">Open all month / month-precision windows</h3>
      <p className="text-xs leading-5 text-muted-foreground">These windows are recorded by month. See each item for its opening range and official or tentative basis.</p>
      {monthItems.map((item) => <ItemRow key={item.id} item={item} onSelect={onSelect} />)}
    </section>}
  </section>;
}
