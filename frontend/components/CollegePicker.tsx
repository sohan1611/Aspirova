"use client";

import { Check, ChevronDown, Search } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const collegeListCache = new Map<string, Promise<string[]>>();
const COLLEGE_BATCH_SIZE = 200;

function loadColleges(countryCode: string): Promise<string[]> {
  const cachedColleges = collegeListCache.get(countryCode);
  if (cachedColleges) return cachedColleges;

  const collegeRequest = fetch("/colleges/" + countryCode + ".json")
    .then(async (response): Promise<unknown> => {
      if (!response.ok) return [];
      return response.json();
    })
    .then((data: unknown) => {
      if (!Array.isArray(data)) return [];
      return data.filter((college): college is string => typeof college === "string");
    })
    .catch(() => []);

  collegeListCache.set(countryCode, collegeRequest);
  return collegeRequest;
}

export interface CollegePickerProps {
  countryCode: string | null;
  value: string | null;
  onSelect: (college: string) => void;
  onOther: () => void;
  id?: string;
}

export function CollegePicker({
  countryCode,
  value,
  onSelect,
  onOther,
  id,
}: CollegePickerProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [loadedCollegeList, setLoadedCollegeList] = React.useState<{
    countryCode: string;
    colleges: string[];
  } | null>(null);
  const [visibleCollegeCount, setVisibleCollegeCount] = React.useState(
    COLLEGE_BATCH_SIZE,
  );
  const searchInputRef = React.useRef<HTMLInputElement>(null);
  const searchInputId = React.useId();
  const collegeListId = React.useId();
  const resultCountId = React.useId();
  const normalizedCountryCode = countryCode?.trim().toUpperCase() || null;

  React.useEffect(() => {
    if (!open || !normalizedCountryCode) return;

    let cancelled = false;

    void loadColleges(normalizedCountryCode).then((colleges) => {
      if (!cancelled) {
        setLoadedCollegeList({ countryCode: normalizedCountryCode, colleges });
        setVisibleCollegeCount(COLLEGE_BATCH_SIZE);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [normalizedCountryCode, open]);

  const colleges =
    loadedCollegeList?.countryCode === normalizedCountryCode
      ? loadedCollegeList.colleges
      : null;

  const matchingColleges = React.useMemo(() => {
    if (!colleges) return [];

    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return colleges;

    return colleges.filter((college) =>
      college.toLocaleLowerCase().includes(normalizedQuery),
    );
  }, [colleges, query]);

  const visibleMatchingColleges = React.useMemo(
    () => matchingColleges.slice(0, visibleCollegeCount),
    [matchingColleges, visibleCollegeCount],
  );

  const handleOpenChange = React.useCallback((nextOpen: boolean) => {
    setVisibleCollegeCount(COLLEGE_BATCH_SIZE);
    setOpen(nextOpen);
    if (!nextOpen) setQuery("");
  }, []);

  const handleCollegeListScroll = React.useCallback(
    (event: React.UIEvent<HTMLUListElement>) => {
      const list = event.currentTarget;

      if (list.scrollTop + list.clientHeight >= list.scrollHeight - 200) {
        setVisibleCollegeCount((count) =>
          Math.min(count + COLLEGE_BATCH_SIZE, matchingColleges.length),
        );
      }
    },
    [matchingColleges.length],
  );

  function handleSelect(college: string) {
    onSelect(college);
    handleOpenChange(false);
  }

  function handleOther() {
    handleOpenChange(false);
    onOther();
  }

  const trigger = (
    <Button
      id={id}
      type="button"
      variant="outline"
      disabled={!normalizedCountryCode}
      className="w-full justify-between font-normal"
    >
      <span className="min-w-0 flex-1 truncate text-left">
        {value?.trim() ? value : "Select your college"}
      </span>
      <ChevronDown className="shrink-0 text-muted-foreground" aria-hidden="true" />
    </Button>
  );

  if (!normalizedCountryCode) return trigger;

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label="Choose your college"
        className="w-[min(22rem,calc(100vw-2rem))] p-2"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchInputRef.current?.focus();
        }}
      >
        <div className="relative">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <label htmlFor={searchInputId} className="sr-only">
            Search colleges
          </label>
          <Input
            ref={searchInputRef}
            id={searchInputId}
            type="search"
            value={query}
            onChange={(event) => {
              setVisibleCollegeCount(COLLEGE_BATCH_SIZE);
              setQuery(event.target.value);
            }}
            placeholder="Search colleges..."
            autoComplete="off"
            aria-controls={collegeListId}
            aria-describedby={resultCountId}
            className="pl-9"
          />
        </div>

        <p id={resultCountId} className="sr-only" aria-live="polite">
          {colleges === null
            ? "Loading colleges"
            : matchingColleges.length +
              " " +
              (matchingColleges.length === 1 ? "college" : "colleges") +
              " available"}
        </p>

        <ul
          id={collegeListId}
          aria-label="Colleges"
          className="mt-2 max-h-72 space-y-0.5 overflow-y-auto pr-1"
          onScroll={handleCollegeListScroll}
        >
          {colleges === null ? (
            <li className="px-2 py-6 text-center text-sm text-muted-foreground">
              Loading colleges…
            </li>
          ) : colleges.length === 0 ? (
            <li className="px-2 py-6 text-center text-sm text-muted-foreground">
              No college list for this country yet.
            </li>
          ) : matchingColleges.length === 0 ? (
            <li className="px-2 py-6 text-center text-sm text-muted-foreground">
              No colleges match “{query.trim()}”.
            </li>
          ) : (
            visibleMatchingColleges.map((college) => {
              const isSelected = college === value;

              return (
                <li key={college}>
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => handleSelect(college)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-sm px-2 py-2 text-left text-sm transition-colors duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isSelected
                        ? "bg-accent text-accent-foreground"
                        : "hover:bg-accent/70 hover:text-accent-foreground",
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate">{college}</span>
                    {isSelected && (
                      <Check
                        className="size-4 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                    )}
                  </button>
                </li>
              );
            })
          )}
        </ul>

        <div className="mt-2 border-t border-border pt-2">
          <button
            type="button"
            onClick={handleOther}
            className={cn(
              "flex w-full items-center rounded-sm px-2 py-2 text-left text-sm transition-colors duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "hover:bg-accent/70 hover:text-accent-foreground",
            )}
          >
            Other — enter manually
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export default CollegePicker;
