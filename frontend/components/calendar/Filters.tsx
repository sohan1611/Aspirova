"use client";

import { Search } from "lucide-react";
import { CountedAdvancedFilterShell } from "@/components/CountedAdvancedFilterShell";
import { FilterPanelSection } from "@/components/CountedFilterControls";
import { Button } from "@/components/ui/button";
import { CALENDAR_CATEGORIES,categoryColour,categoryLabel,collapseRecurrences,filterCalendarItems } from "@/lib/hiringCalendar";
import type { CalendarItem,CalendarQuery } from "@/lib/hiringCalendar";
import { CALENDAR_FOCUS,CALENDAR_INPUT } from "./CalendarItem";

const STATUS_LABELS: Record<string,string>={
  announced: "Official upcoming",
  expected: "Tentative",
  closed: "Closed",
};

export default function CalendarFilters({ query,search,onSearch,items,today,onChange,onClear }: {
  query: CalendarQuery; search: string; onSearch: (search: string) => void;
  items: CalendarItem[]; today: string; onChange: (query: CalendarQuery) => void; onClear: () => void;
}) {
  const keys=[...new Set([...CALENDAR_CATEGORIES.map(([key]) => key),...items.map((item) => item.programme.category),...query.category])];
  const faceted=filterCalendarItems(items,{ ...query,category: [] },today);
  function count(category?: string) {
    const values=category? faceted.filter((item) => item.programme.category===category):faceted;
    const collapsed=collapseRecurrences(values,today);
    return collapsed.dated.length+collapsed.recurring.length;
  }
  function toggleCategory(category: string) {
    onChange({ ...query,category: query.category.includes(category)? query.category.filter((value) => value!==category):[...query.category,category] });
  }
  const activeCount=query.category.length+Number(!!query.status)+Number(query.closingSoon)+Number(query.officialOnly);
  const categoryControls=(
    <div role="group" aria-label="Categories" className="flex min-w-0 flex-wrap gap-2">
      <button
        type="button"
        aria-pressed={!query.category.length}
        onClick={() => onChange({ ...query,category: [] })}
        className={`min-h-11 rounded-full border px-3 text-xs font-medium ${!query.category.length? "border-primary bg-accent text-primary":"border-border bg-card"} ${CALENDAR_FOCUS}`}
      >
        All <span className="ml-1 text-muted-foreground">{count()}</span>
      </button>
      {keys.map((key) => (
        <button
          key={key}
          type="button"
          aria-pressed={query.category.includes(key)}
          onClick={() => toggleCategory(key)}
          className={`inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-full border px-3 py-2 text-left text-xs font-medium ${query.category.includes(key)? "border-primary bg-accent text-primary":"border-border bg-card hover:bg-secondary"} ${CALENDAR_FOCUS}`}
        >
          <span className="size-2 shrink-0 rounded-full" aria-hidden="true" style={{ backgroundColor: categoryColour(key) }} />
          {categoryLabel(key,items.find((item) => item.programme.category===key)?.programme.category_label)}
          <span className="text-muted-foreground">{count(key)}</span>
        </button>
      ))}
    </div>
  );
  const quickControls=(
    <div className="flex flex-wrap gap-2" role="group" aria-label="Quick filters">
      {[
        { label: "Open now",active: query.status==="open",change: { status: query.status==="open"? "":"open" } },
        { label: "Closing soon (≤ 30 days)",active: query.closingSoon,change: { closingSoon: !query.closingSoon } },
        { label: "Official dates only",active: query.officialOnly,change: { officialOnly: !query.officialOnly } },
      ].map(({ label,active,change }) => (
        <Button
          key={label}
          variant="outline"
          className={`min-h-11 text-xs ${active? "border-success/40 bg-success/10 text-success":"text-muted-foreground"}`}
          aria-pressed={active}
          onClick={() => onChange({ ...query,...change })}
        >{label}</Button>
      ))}
      {query.status&&query.status!=="open"&&(
        <Button variant="outline" className="min-h-11" onClick={() => onChange({ ...query,status: "" })}>
          {STATUS_LABELS[query.status]??query.status} ×
        </Button>
      )}
    </div>
  );

  return (
    <section aria-label="Search and filter calendar" className="space-y-3">
      <div className="flex min-w-0 items-center gap-2">
        <label className="relative block min-w-0 flex-1">
          <span className="sr-only">Search a company, event or exam</span>
          <Search className="pointer-events-none absolute top-3.5 left-3 size-5 text-muted-foreground" aria-hidden="true" />
          <input
            type="search"
            maxLength={200}
            placeholder="Search a company, event or exam"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            className={`${CALENDAR_INPUT} h-12 w-full pl-10`}
          />
        </label>
        <div className="md:hidden [&_button]:min-h-11">
          <CountedAdvancedFilterShell
            activeFilterCount={activeCount}
            activeFilterLabel="calendar filters"
            isPending={false}
            panelLabel="Calendar filters"
            mobileDescription="Choose categories and registration status."
            idPrefixBase="calendar"
            mobileContentClassName="[&>button]:min-h-11 [&>button]:min-w-11"
          >
            {({ onClose }) => (
              <div className="space-y-5 p-4">
                <FilterPanelSection title="Categories">{categoryControls}</FilterPanelSection>
                <FilterPanelSection title="Registration status">{quickControls}</FilterPanelSection>
                <div className="flex gap-2">
                  <Button variant="outline" className="min-h-11" onClick={onClear}>Clear filters</Button>
                  <Button className="min-h-11" onClick={onClose}>Show results</Button>
                </div>
              </div>
            )}
          </CountedAdvancedFilterShell>
        </div>
      </div>
      <div className="hidden space-y-3 md:block">{categoryControls}{quickControls}</div>
      {activeCount>0&&(
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground md:hidden">
          <span>{activeCount} active filters</span>
          <Button variant="ghost" className="min-h-11 text-xs" onClick={onClear}>Clear filters</Button>
        </div>
      )}
    </section>
  );
}
