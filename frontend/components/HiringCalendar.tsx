"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import CalendarFilters from "@/components/calendar/Filters";
import OpenNow from "@/components/calendar/OpenNow";
import PeriodControl from "@/components/calendar/PeriodControl";
import MonthList, { AnytimeSection, RecurringSection } from "@/components/calendar/MonthList";
import Timeline from "@/components/calendar/Timeline";
import MonthGrid from "@/components/calendar/MonthGrid";
import DetailsDrawer from "@/components/calendar/DetailsDrawer";
import { calendarParams, collapseRecurrences, fetchCalendar, filterCalendarItems, monthRange, parseCalendarParams, registrationEvents, todayIST } from "@/lib/hiringCalendar";
import type { CalendarItem, CalendarQuery, CalendarResponse } from "@/lib/hiringCalendar";

export default function HiringCalendar({ initialQuery, initialData }: {
  initialQuery: CalendarQuery; initialData: CalendarResponse | null;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [data, setData] = useState(initialData);
  const [today, setToday] = useState(initialQuery.from);
  const [search, setSearch] = useState(initialQuery.q);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const queryRef = useRef(query);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const fallbackFocus = useRef<HTMLDivElement>(null);
  const skipInitialFetch = useRef(!!initialData);

  const change = useCallback((next: CalendarQuery, replace = false) => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    queryRef.current = next;
    setQuery(next);
    setSearch(next.q);
    const href = `/calendar?${calendarParams(next)}`;
    if (replace) {
      window.history.replaceState(null, "", href);
    } else {
      window.history.pushState(null, "", href);
    }
  }, []);

  useEffect(() => {
    const restore = () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
      const next = parseCalendarParams(new URLSearchParams(window.location.search), todayIST());
      queryRef.current = next;
      setQuery(next);
      setSearch(next.q);
      setToday(todayIST());
    };
    queueMicrotask(restore);
    window.addEventListener("popstate", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, []);

  useEffect(() => {
    if (skipInitialFetch.current && query.from === initialQuery.from && query.to === initialQuery.to && retry === 0) {
      skipInitialFetch.current = false;
      return;
    }
    skipInitialFetch.current = false;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        setLoading(true);
        setError("");
      }
    });
    void fetchCalendar(queryRef.current, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("The calendar could not be loaded. Try again.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [query.from, query.to, retry, initialQuery.from, initialQuery.to]);

  function updateSearch(value: string) {
    setSearch(value);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => change({ ...queryRef.current, q: value.trim() }, true), 220);
  }

  function clearFilters() {
    change({ ...query, category: [], status: "", closingSoon: false, officialOnly: false, q: "" });
  }

  function changeWithSearch(next: CalendarQuery) {
    change({ ...next, q: search.trim() });
  }

  function selectItem(item: CalendarItem) {
    lastTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    changeWithSearch({ ...query, item: item.id });
  }

  const all = useMemo(() => {
    const entries = [...(data?.items ?? []), ...(data?.rolling ?? [])];
    return [...new Map(entries.map((item) => [item.id, item])).values()];
  }, [data]);
  const filtered = filterCalendarItems(all, query, today);
  const rollingIds = new Set(data?.rolling.map((item) => item.id) ?? []);
  const undated = filtered.filter((item) => rollingIds.has(item.id) || !registrationEvents(item).length);
  const dated = filtered.filter((item) => !undated.includes(item));
  const collapsed = collapseRecurrences(dated, today);
  const count = collapsed.dated.length + collapsed.recurring.length + undated.length;
  const range = data ? { from: data.from, to: data.to } : query;
  const previousPeriod = range.from !== query.from || range.to !== query.to;
  const selectedItem = all.find((item) => item.id === query.item) ?? null;

  return (
    <div className="mt-4 min-w-0 space-y-5">
      <CalendarFilters
        query={query}
        search={search}
        onSearch={updateSearch}
        items={all}
        today={today}
        onChange={changeWithSearch}
        onClear={clearFilters}
      />
      <OpenNow items={filtered} today={today} onSelect={selectItem} />
      <div id="calendar-results" tabIndex={-1} ref={fallbackFocus} className="min-w-0 scroll-mt-20 space-y-4 outline-none">
        <PeriodControl query={query} today={today} onChange={changeWithSearch} />
        <div role="status" aria-live="polite" className="flex min-h-5 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {loading ? (
            <>
              <Skeleton className="h-1 w-16 motion-reduce:animate-none" />
              <span>{previousPeriod ? "Updating period · previous results shown below" : "Updating calendar…"}</span>
            </>
          ) : <span>{count} {count === 1 ? "programme" : "programmes"}</span>}
        </div>
        {error && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/25 bg-red-50 p-3 text-sm">
            <p>{error}{previousPeriod ? " Previous results are shown below." : ""}</p>
            <Button variant="outline" className="min-h-11" onClick={() => setRetry((value) => value + 1)}>Try again</Button>
          </div>
        )}
        {!data && loading && (
          <div className="space-y-3" aria-label="Loading calendar">
            <Skeleton className="h-24 motion-reduce:animate-none" />
            <Skeleton className="h-24 motion-reduce:animate-none" />
            <Skeleton className="h-24 motion-reduce:animate-none" />
          </div>
        )}
        {data && count === 0 && (
          <section className="rounded-xl border border-dashed border-border px-5 py-10 text-center">
            <h2 className="font-serif text-xl font-semibold">No programmes match these filters</h2>
            <p className="mt-2 text-sm text-muted-foreground">Try another company, event or exam, or clear the filters.</p>
            <Button variant="outline" className="mt-4 min-h-11" onClick={clearFilters}>Clear filters</Button>
          </section>
        )}
        {data && count > 0 && (
          <section aria-label="Calendar results" aria-busy={loading} className={`min-w-0 space-y-7 ${loading ? "opacity-70" : ""}`}>
            {query.view === "list" && (
              <MonthList items={collapsed.dated} recurring={collapsed.recurring} range={range} onSelect={selectItem} />
            )}
            {query.view === "timeline" && (
              <Timeline items={collapsed.dated} recurring={collapsed.recurring} range={range} today={today} onSelect={selectItem} />
            )}
            {query.view === "grid" && (
              <>
                <MonthGrid
                  key={`${range.from}-${range.to}`}
                  items={dated}
                  range={range}
                  today={today}
                  onSelect={selectItem}
                  onOutsideMonth={(month) => changeWithSearch({ ...query, ...monthRange(month), period: "month" })}
                />
                <RecurringSection rows={collapsed.recurring} onSelect={selectItem} />
              </>
            )}
            <AnytimeSection items={undated} onSelect={selectItem} />
          </section>
        )}
      </div>
      <DetailsDrawer
        key={query.item}
        item={selectedItem}
        query={query}
        recurringRule={collapsed.recurring.find(({ item }) => item.programme.slug === selectedItem?.programme.slug)?.rule}
        loading={loading}
        onClose={() => change({ ...query, item: "" })}
        onRestoreFocus={() => {
          if (lastTrigger.current?.isConnected) lastTrigger.current.focus();
          else fallbackFocus.current?.focus();
        }}
      />
    </div>
  );
}
