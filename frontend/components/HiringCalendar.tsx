"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadedList, failedList, type ListState } from "@/lib/listState";
import { ListingFailure, ListingEmpty, ListingSnapshotNotice } from "@/components/ListingFeedback";
import { Skeleton } from "@/components/ui/skeleton";
import CalendarFilters from "@/components/calendar/Filters";
import OpenNow from "@/components/calendar/OpenNow";
import PeriodControl from "@/components/calendar/PeriodControl";
import MonthList, { AnytimeSection, RecurringSection } from "@/components/calendar/MonthList";
import Timeline from "@/components/calendar/Timeline";
import MonthGrid from "@/components/calendar/MonthGrid";
import DetailsDrawer from "@/components/calendar/DetailsDrawer";
import { ProgrammeWatchSummary } from "@/components/calendar/ProgrammeWatches";
import { calendarParams, collapseRecurrences, fetchCalendar, filterCalendarItems, monthRange, parseCalendarParams, registrationEvents, todayIST } from "@/lib/hiringCalendar";
import type { CalendarItem, CalendarQuery, CalendarResponse } from "@/lib/hiringCalendar";

export default function HiringCalendar({ initialQuery, initialData }: {
  initialQuery: CalendarQuery; initialData: CalendarResponse | null;
}) {
  return <HiringCalendarContent initialQuery={initialQuery} initialData={initialData} />;
}

function HiringCalendarContent({ initialQuery, initialData }: {
  initialQuery: CalendarQuery; initialData: CalendarResponse | null;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [state, setState] = useState<ListState<CalendarResponse> | null>(initialData ? loadedList(initialData, initialData.items.length + initialData.rolling.length, initialData.loadedAt) : failedList<CalendarResponse>(null));
  const data = state?.data ?? null;
  const error = state?.status === "failed";
  const [today, setToday] = useState(initialQuery.from);
  const [search, setSearch] = useState(initialQuery.q);
  const [loading, setLoading] = useState(false);
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
      }
    });
    void fetchCalendar(queryRef.current, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setState(loadedList(result, result.items.length + result.rolling.length, result.loadedAt));
      })
      .catch(() => {
        if (!controller.signal.aborted) setState(previous => failedList(previous));
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
      <ProgrammeWatchSummary />
      <CalendarFilters
        query={query}
        search={search}
        onSearch={updateSearch}
        items={all}
        countsKnown={!!data && !error && !loading}
        today={today}
        onChange={changeWithSearch}
        onClear={clearFilters}
      />
      {!error && <OpenNow items={filtered} today={today} onSelect={selectItem} />}
      <div id="calendar-results" tabIndex={-1} ref={fallbackFocus} className="min-w-0 scroll-mt-20 space-y-4 outline-none">
        <PeriodControl query={query} today={today} onChange={changeWithSearch} />
        <div role="status" aria-live="polite" className="flex min-h-5 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {loading ? (
            <>
              <Skeleton className="h-1 w-16 motion-reduce:animate-none" />
              <span>{previousPeriod ? "Updating period · previous results shown below" : "Updating calendar…"}</span>
            </>
          ) : !error && data ? <span>{count} {count === 1 ? "programme" : "programmes"}</span> : null}
        </div>
        {error && <ListingFailure retry={() => setRetry(value => value + 1)} loadedAt={data && count > 0 ? state?.loadedAt : null} pending={loading} />}
        {state?.loadedAt && !error && <ListingSnapshotNotice loadedAt={state.loadedAt} expiresAt={data?.expiresAt} />}
        {!data && loading && (
          <div className="space-y-3" aria-label="Loading calendar">
            <Skeleton className="h-24 motion-reduce:animate-none" />
            <Skeleton className="h-24 motion-reduce:animate-none" />
            <Skeleton className="h-24 motion-reduce:animate-none" />
          </div>
        )}
        {data && !error && !loading && count === 0 && <ListingEmpty pathname="/calendar" query={calendarParams(query).toString()} title="No programmes match these filters." navigate={href => change(parseCalendarParams(new URL(href, window.location.origin).searchParams, today))} />}
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
