"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CALENDAR_CATEGORIES, calendarDays, calendarParams, currentCycleYear, dateLabel,
  fetchCalendar, itemDate, monthRange, openingInMonth, parseCalendarParams, presetRange, programmeSummaryName, rangeError,
  shiftMonth, todayIST, windowText,
} from "@/lib/hiringCalendar";
import type { CalendarItem, CalendarQuery, CalendarResponse, CalendarView } from "@/lib/hiringCalendar";

const INPUT = "min-h-11 min-w-0 max-w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function CalendarCard({ item }: { item: CalendarItem; }) {
  return (
    <article className="min-w-0 rounded-xl border border-border bg-card p-4 shadow-soft sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{item.programme.category_label}</Badge>
        <Badge variant={item.is_open_now ? "default" : "outline"}>{item.edition.status_label}</Badge>
      </div>
      <h3 className="mt-3 break-words font-serif text-lg font-semibold">{item.programme.name}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{item.programme.organiser} · {item.edition.year} cycle</p>
      <p className="mt-3 text-sm font-medium">{windowText(item)}</p>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.programme.eligibility}</p>
      {item.programme.geography && <p className="mt-2 text-sm text-muted-foreground">{item.programme.geography}</p>}
      {item.metadata.hiring_mode && <p className="mt-2 text-sm leading-6">{item.metadata.hiring_mode}</p>}
      {item.metadata.duration_start && (
        <p className="mt-2 text-sm text-muted-foreground">
          {item.metadata.source_cycle_year !== item.edition.year && `Source cycle ${item.metadata.source_cycle_year} · `}
          {item.metadata.duration_start}
        </p>
      )}
      <details className="mt-3 border-t border-border text-sm">
        <summary className={`flex min-h-11 cursor-pointer items-center font-medium ${FOCUS}`}>Preparation and programme details</summary>
        <div className="space-y-2 pb-3 leading-6 text-muted-foreground">
          <p>{item.metadata.prep_tip}</p>
          <p>{item.metadata.career_linkage}</p>
          <p>{item.metadata.verification_note}</p>
          {item.edition.status_label === "Rolling" && <p>Source cycle {item.metadata.source_cycle_year} guidance · {item.metadata.opening_text} · {item.metadata.deadline_text}</p>}
        </div>
      </details>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Button variant="outline" asChild className="min-h-11">
          <a href={item.programme.url} target="_blank" rel="noopener noreferrer">Official site ↗</a>
        </Button>
        <p className="text-xs text-muted-foreground">
          {item.verified_at ? `Last checked ${dateLabel(item.verified_at)}` : "Awaiting a current-cycle check"}
        </p>
      </div>
    </article>
  );
}

function agendaGroup(item: CalendarItem, query: CalendarQuery): string {
  const edition = item.edition;
  const candidates = item.metadata.deadline_rolling ? [
    [edition.opens_at, edition.opens_precision],
  ] : [
    [edition.closes_at, edition.closes_precision],
    [edition.opens_at, edition.opens_precision],
  ];
  for (const [value, precision] of candidates) {
    if (!value) continue;
    const day = itemDate(value);
    if (day >= query.from && day <= query.to) return precision === "month" ? day.slice(0, 7) : day;
  }
  if (item.metadata.deadline_rolling && edition.opens_precision === "month" &&
      openingInMonth(item, query.from.slice(0, 7))) return query.from.slice(0, 7);
  return "Continuing windows";
}

function Agenda({ items, query }: { items: CalendarItem[]; query: CalendarQuery; }) {
  const groups = new Map<string, CalendarItem[]>();
  for (const item of items) {
    const key = agendaGroup(item, query);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  if (!items.length) return <p className="py-8 text-sm text-muted-foreground">No dated windows match this range and these filters.</p>;
  return (
    <div className="space-y-6">
      {[...groups].sort(([left], [right]) => left.localeCompare(right)).map(([group, values]) => (
        <section key={group}>
          <h2 className="mb-3 font-serif text-xl font-semibold">
            {group === "Continuing windows" ? group : dateLabel(`${group}${group.length === 7 ? "-01" : ""}T12:00:00Z`, group.length === 7 ? "month" : "day")}
          </h2>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">{values.map((item) => <CalendarCard key={item.id} item={item} />)}</div>
        </section>
      ))}
    </div>
  );
}

export default function HiringCalendar({ initialQuery, initialData }: {
  initialQuery: CalendarQuery; initialData: CalendarResponse | null;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [custom, setCustom] = useState({ from: initialQuery.from, to: initialQuery.to });
  const [selectedDay, setSelectedDay] = useState("");
  const activeRequest = useRef<AbortController | null>(null);

  const load = useCallback((next: CalendarQuery, push = true) => {
    activeRequest.current?.abort();
    setQuery(next);
    setCustom({ from: next.from, to: next.to });
    setSelectedDay("");
    setError("");
    if (push) window.history.pushState(null, "", `/calendar?${calendarParams(next)}`);
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setData(null);
    void fetchCalendar(next, { signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) setData(result);
    }).catch(() => {
      if (!controller.signal.aborted) setError("The calendar could not be loaded. Try again.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
  }, []);

  useEffect(() => {
    const restore = () => load(parseCalendarParams(new URLSearchParams(window.location.search), todayIST()), false);
    const next = parseCalendarParams(new URLSearchParams(window.location.search), todayIST());
    if (!initialData || calendarParams(next).toString() !== calendarParams(initialQuery).toString()) {
      // Defer URL restoration until hydration has preserved the static HTML.
      queueMicrotask(() => load(next, false));
    }
    window.addEventListener("popstate", restore);
    return () => { window.removeEventListener("popstate", restore); activeRequest.current?.abort(); };
  }, [initialData, initialQuery, load]);

  function chooseView(view: CalendarView) {
    const today = todayIST();
    const range = view === "custom" ? { from: query.from, to: query.to } : presetRange(view, today, {
      year: Number(query.from.slice(0, 4)), month: query.from.slice(0, 7), days: query.days,
    });
    load({ ...query, ...range, view });
  }

  function openMonth(month: string) {
    load({ ...query, ...monthRange(month), view: "month" });
  }

  const customError = rangeError(custom.from, custom.to);
  const year = Number(query.from.slice(0, 4));
  const years = [...new Set([year, ...Array.from({ length: 7 }, (_, index) => currentCycleYear(todayIST()) - 2 + index)])].sort();
  const month = query.from.slice(0, 7);
  const items = data?.items ?? [];
  const dayItems = selectedDay ? items.filter((item) =>
    (item.edition.opens_precision === "day" && item.edition.opens_at && itemDate(item.edition.opens_at) === selectedDay) ||
    (!item.metadata.deadline_rolling && item.edition.closes_precision === "day" && item.edition.closes_at && itemDate(item.edition.closes_at) === selectedDay)) : items;

  return (
    <div className="mt-6 min-w-0">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Calendar range">
        {([["year", "Full year"], ["month", "Month"], ["days", "Days"], ["custom", "Custom range"]] as const).map(([view, label]) => (
          <Button
            key={view}
            variant={query.view === view ? "default" : "outline"}
            className="min-h-11"
            aria-pressed={query.view === view}
            onClick={() => chooseView(view)}
          >{label}</Button>
        ))}
      </div>
      <div className="mt-4 flex min-w-0 flex-wrap items-end gap-3">
        {query.view === "year" && <label className="grid gap-1 text-sm">Year
          <select
            className={INPUT}
            value={year}
            onChange={(event) => load({ ...query, ...presetRange("year", todayIST(), { year: Number(event.target.value) }) })}
          >
            {years.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>}
        {query.view === "month" && <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
          <Button
            className="min-h-11 min-w-11"
            variant="outline"
            aria-label="Previous month"
            onClick={() => openMonth(shiftMonth(month, -1))}
          >‹</Button>
          <label className="grid min-w-0 flex-1 gap-1 text-sm">Month
            <input
              type="month"
              className={`${INPUT} w-full`}
              value={month}
              onChange={(event) => { if (/^\d{4}-\d{2}$/.test(event.target.value)) openMonth(event.target.value); }}
            />
          </label>
          <Button
            className="min-h-11 min-w-11"
            variant="outline"
            aria-label="Next month"
            onClick={() => openMonth(shiftMonth(month, 1))}
          >›</Button>
        </div>}
        {query.view === "days" && <div className="flex flex-wrap gap-2" role="group" aria-label="Days from today">
          {([7, 30, 90] as const).map((days) => <Button
            key={days}
            className="min-h-11"
            variant={query.days === days ? "default" : "outline"}
            aria-pressed={query.days === days}
            onClick={() => load({ ...query, ...presetRange("days", todayIST(), { days }), days })}
          >Next
            {days} days
          </Button>)}
        </div>}
        {query.view === "custom" && <form
          className="flex w-full min-w-0 flex-wrap items-end gap-3"
          onSubmit={(event) => { event.preventDefault(); if (!customError) load({ ...query, ...custom }); }}
        >
          <label className="grid min-w-0 flex-1 basis-36 gap-1 text-sm">From
            <input
              type="date"
              required
              className={`${INPUT} w-full`}
              value={custom.from}
              aria-describedby="calendar-range-error"
              onChange={(event) => setCustom({ ...custom, from: event.target.value })}
            />
          </label>
          <label className="grid min-w-0 flex-1 basis-36 gap-1 text-sm">To
            <input
              type="date"
              required
              className={`${INPUT} w-full`}
              value={custom.to}
              aria-describedby="calendar-range-error"
              onChange={(event) => setCustom({ ...custom, to: event.target.value })}
            />
          </label>
          <Button className="min-h-11" disabled={!!customError}>Show range</Button>
          <p id="calendar-range-error" className="w-full text-sm text-destructive" aria-live="polite">{customError}</p>
        </form>}
      </div>
      <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="Categories">
        <Button
          variant={query.category.length ? "outline" : "default"}
          className="min-h-11"
          aria-pressed={!query.category.length}
          onClick={() => load({ ...query, category: [] })}
        >All</Button>
        {CALENDAR_CATEGORIES.map(([key, label]) => <Button
          key={key}
          className="min-h-11"
          variant={query.category.includes(key) ? "default" : "outline"}
          aria-pressed={query.category.includes(key)}
          onClick={() => load({ ...query, category: query.category.includes(key) ? query.category.filter((value) => value !== key) : [...query.category, key] })}
        >{label}</Button>)}
      </div>
      <form
        className="mt-4 flex min-w-0 flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault(); const form = new FormData(event.currentTarget);
          load({ ...query, q: String(form.get("q") ?? "").trim().slice(0, 200) });
        }}
      >
        <label className="grid min-w-0 gap-1 text-sm">Status
          <select
            className={INPUT}
            value={query.status}
            onChange={(event) => load({ ...query, status: event.target.value })}
          >
            <option value="">All statuses</option>
            <option value="open">Open now</option>
            <option value="announced">Official upcoming</option>
            <option value="expected">Tentative</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <label className="grid min-w-0 flex-1 basis-40 gap-1 text-sm">Programme or organiser
          <input
            key={query.q}
            name="q"
            type="search"
            maxLength={200}
            defaultValue={query.q}
            className={`${INPUT} w-full`}
          />
        </label>
        <Button className="min-h-11" variant="outline">Search</Button>
      </form>
      <p className="my-5 text-sm text-muted-foreground">
        {`${dateLabel(`${query.from}T12:00:00Z`)} – ${dateLabel(`${query.to}T12:00:00Z`)}`}
      </p>
      <div aria-live="polite" role="status" className="text-sm">{loading ? "Loading calendar…" : error}</div>
      {error && <Button className="mt-3 min-h-11" variant="outline" onClick={() => load(query, false)}>Try again</Button>}
      {data && <section aria-label="Calendar results">
        {query.view === "year" && <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.months.map(({ month: key, count }) => {
            const highlights = items.filter((item) => item.metadata.deadline_rolling
              ? openingInMonth(item, key)
              : item.edition.closes_at && itemDate(item.edition.closes_at).startsWith(key)
            ).sort((left, right) => {
              const leftDate = left.metadata.deadline_rolling ? left.edition.opens_at! : left.edition.closes_at!;
              const rightDate = right.metadata.deadline_rolling ? right.edition.opens_at! : right.edition.closes_at!;
              return leftDate.localeCompare(rightDate);
            }).slice(0, 3);
            return <button
              type="button"
              key={key}
              className={`flex min-h-36 min-w-0 flex-col items-stretch justify-start rounded-xl border border-border p-4 text-left transition-colors hover:bg-accent ${count ? "bg-card" : "bg-secondary/30"} ${FOCUS}`}
              onClick={() => openMonth(key)}
              aria-label={`${dateLabel(`${key}-01T12:00:00Z`, "month")}, ${count} windows`}
            >
              <span className="flex items-center justify-between gap-2">

                <span className="font-serif text-lg font-semibold">{dateLabel(`${key}-01T12:00:00Z`, "month")}</span>

                <Badge variant={count ? "default" : "secondary"}>{count}</Badge>
              </span>
              <span className="mt-2 block text-xs text-muted-foreground">{count} intersecting windows</span>
              {highlights.map((item) => <span key={item.id} className="mt-2 block break-words text-sm">

                {item.metadata.deadline_rolling
                  ? item.edition.opens_precision === "day" ? `Opens ${dateLabel(item.edition.opens_at!)} · ` : "Opening window · "
                  : item.edition.closes_precision === "day" ? `${dateLabel(item.edition.closes_at!)} · ` : "Deadline month · "}

                {programmeSummaryName(item.programme)}
              </span>)}
            </button>;
          })}
        </div>}
        {query.view === "month" && <>
          <div
            className="mb-6 overflow-hidden rounded-xl border border-border bg-card p-1 sm:p-3"
            aria-label="Opening and deadline dates"
          >
            <div className="grid grid-cols-7 text-center text-xs text-muted-foreground">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <span key={day} className="py-2">{day}</span>)}</div>
            <div className="grid grid-cols-7">{calendarDays(month).map((day, index) => {
              const opens = day && items.some((item) => item.edition.opens_precision === "day" && item.edition.opens_at && itemDate(item.edition.opens_at) === day);
              const closes = day && items.some((item) => !item.metadata.deadline_rolling && item.edition.closes_precision === "day" && item.edition.closes_at && itemDate(item.edition.closes_at) === day);
              return day ? <button

                key={day}

                type="button"

                className={`flex min-h-12 min-w-0 flex-col items-center justify-center rounded-md text-sm hover:bg-accent aria-pressed:bg-primary aria-pressed:text-primary-foreground ${FOCUS}`}

                aria-pressed={selectedDay === day}

                aria-label={`${dateLabel(`${day}T12:00:00Z`)}${opens ? ", window opens" : ""}${closes ? ", deadline" : ""}`}

                onClick={() => setSelectedDay(selectedDay === day ? "" : day)}
              >


                {Number(day.slice(8))}

                <span className="flex h-2 gap-1" aria-hidden="true">

                  {opens && <span className="size-1.5 rounded-full bg-primary" />}

                  {closes && <span className="size-1.5 rounded-full bg-amber-500" />}

                </span>
              </button> : <span key={`empty-${index}`} />;
            })}</div>
            <p className="px-2 py-3 text-xs text-muted-foreground">Blue marks openings. Amber marks deadlines. Month-precision openings are marked below.</p>
            {items.some((item) => item.edition.opens_precision === "month" && openingInMonth(item, month)) && (
              <section className="border-t border-border px-2 py-3" aria-label="Month-precision openings">
                <h2 className="mb-2 text-sm font-semibold">Opening windows · {dateLabel(`${month}-01T12:00:00Z`, "month")}</h2>
                <ul className="space-y-2">
                  {items.filter((item) => item.edition.opens_precision === "month" && openingInMonth(item, month)).map((item) => (
                    <li key={item.id} className="min-w-0 break-words rounded-md border border-primary/30 bg-accent px-3 py-2 text-sm">{programmeSummaryName(item.programme)}</li>
                  ))}
                </ul>
              </section>
            )}
          </div>
          {selectedDay && <Button variant="outline" className="mb-4 min-h-11" onClick={() => setSelectedDay("")}>Show every window this month</Button>}
        </>}
        {query.view !== "year" && <Agenda items={dayItems} query={query} />}
        <details className="mt-8 rounded-xl border border-border bg-card p-4">
          <summary className={`flex min-h-11 cursor-pointer items-center font-serif text-lg font-semibold ${FOCUS}`}>Rolling and unfixed windows (
            {data.rolling.length})
          </summary>
          <p className="mb-4 text-sm leading-6 text-muted-foreground">These routes have vacancy-specific, campus, lab or unconfirmed timing. Check their live notices and eligibility.</p>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">{data.rolling.map((item) => <CalendarCard key={item.id} item={item} />)}</div>
        </details>
      </section>}
    </div>
  );
}
