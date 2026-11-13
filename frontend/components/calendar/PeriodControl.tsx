"use client";

import { useState } from "react";
import { CalendarDays, ChartNoAxesGantt, ChevronDown, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { dateLabel, periodLabel, periodRange, rangeError, stepPeriod } from "@/lib/hiringCalendar";
import type { CalendarPeriod, CalendarQuery } from "@/lib/hiringCalendar";
import { CALENDAR_FOCUS, CALENDAR_INPUT } from "./CalendarItem";

export default function PeriodControl({ query, today, onChange }: {
  query: CalendarQuery; today: string; onChange: (query: CalendarQuery) => void;
}) {
  const [open, setOpen] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const [custom, setCustom] = useState({ from: query.from, to: query.to });
  const error = rangeError(custom.from, custom.to);
  const presets: { value: CalendarPeriod; label: string }[] = [
    { value: "next12", label: "Next 12 months" },
    { value: "next30", label: "Next 30 days" },
    { value: "next90", label: "Next 90 days" },
    { value: "month", label: "This month" },
    { value: "year-2027", label: "Year 2027" },
    { value: "year-2028", label: "Year 2028" },
  ];
  const label = query.period === "month" && query.from.slice(0, 7) !== today.slice(0, 7)
    ? dateLabel(`${query.from}T12:00:00Z`, "month")
    : query.from !== today && query.period.startsWith("next") ? periodLabel(query).replace(/^Next /, "") : periodLabel(query);

  return (
    <div className="space-y-3 border-b border-border pb-4">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-1">
          <Button
            variant="outline"
            className="min-h-11 min-w-11 px-2"
            aria-label="Previous period"
            disabled={query.period === "custom"}
            onClick={() => onChange(stepPeriod(query, -1))}
          >‹</Button>
          <Popover
            open={open}
            onOpenChange={(value) => {
              setOpen(value);
              if (value) {
                setCustom({ from: query.from, to: query.to });
                setCustomMode(query.period === "custom");
              }
            }}
          >
            <PopoverTrigger asChild>
              <Button variant="outline" className="min-h-11 min-w-0" aria-label={`Period, ${label}`}>
                {label}<ChevronDown aria-hidden="true" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[min(22rem,calc(100vw-2rem))] p-2" aria-label="Choose calendar period">
              <div className="grid grid-cols-2 gap-1">
                {presets.map(({ value, label: option }) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={query.period === value}
                    className={`min-h-11 rounded-md px-2 text-left text-sm hover:bg-accent ${query.period === value ? "bg-accent font-semibold text-primary" : ""} ${CALENDAR_FOCUS}`}
                    onClick={() => {
                      onChange({ ...query, period: value, ...periodRange(value, today) });
                      setOpen(false);
                    }}
                  >{option}</button>
                ))}
              </div>
              <Button variant="ghost" className="mt-1 min-h-11 w-full justify-start" aria-expanded={customMode} onClick={() => setCustomMode(!customMode)}>
                Custom range…
              </Button>
              {customMode && (
                <form
                  className="space-y-3 border-t border-border p-2 pt-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!error) {
                      onChange({ ...query, ...custom, period: "custom" });
                      setOpen(false);
                    }
                  }}
                >
                  <label className="grid min-w-0 gap-1 text-sm">
                    From
                    <input type="date" required className={`${CALENDAR_INPUT} w-full`} value={custom.from}
                      onChange={(event) => setCustom({ ...custom, from: event.target.value })} aria-describedby="calendar-range-error" />
                  </label>
                  <label className="grid min-w-0 gap-1 text-sm">
                    To
                    <input type="date" required className={`${CALENDAR_INPUT} w-full`} value={custom.to}
                      onChange={(event) => setCustom({ ...custom, to: event.target.value })} aria-describedby="calendar-range-error" />
                  </label>
                  <p id="calendar-range-error" className={`text-xs ${error ? "text-destructive" : "text-muted-foreground"}`} aria-live="polite">
                    {error ?? "Choose up to two years. Dates use IST."}
                  </p>
                  <Button className="min-h-11" disabled={!!error}>Show range</Button>
                </form>
              )}
            </PopoverContent>
          </Popover>
          <Button
            variant="outline"
            className="min-h-11 min-w-11 px-2"
            aria-label="Next period"
            disabled={query.period === "custom"}
            onClick={() => onChange(stepPeriod(query, 1))}
          >›</Button>
        </div>
        <div className="flex w-full min-w-0 rounded-lg border border-border bg-muted p-1 sm:w-auto" role="group" aria-label="Calendar view">
          {([
            { value: "list", label: "Month by month", Icon: List },
            { value: "timeline", label: "Timeline", Icon: ChartNoAxesGantt },
            { value: "grid", label: "Calendar grid", Icon: CalendarDays },
          ] as const).map(({ value, label: option, Icon }) => (
            <button
              key={value}
              type="button"
              aria-pressed={query.view === value}
              onClick={() => onChange({ ...query, view: value })}
              className={`inline-flex min-h-11 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-md px-2 text-xs font-medium sm:flex-none sm:px-3 sm:text-sm ${query.view === value ? "bg-card text-primary shadow-xs" : "text-muted-foreground hover:text-foreground"} ${CALENDAR_FOCUS}`}
            >
              <Icon className="hidden size-4 sm:block" aria-hidden="true" />{option}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{dateLabel(`${query.from}T12:00:00Z`)} – {dateLabel(`${query.to}T12:00:00Z`)} · IST</p>
    </div>
  );
}
