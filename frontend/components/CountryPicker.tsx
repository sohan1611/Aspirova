"use client";

import { Check, ChevronDown, Search } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { COUNTRIES, getCountry } from "@/lib/countries";
import { cn } from "@/lib/utils";

export interface CountryPickerProps {
  value?: string | null;
  onSelect: (code: string) => void;
  children?: React.ReactElement;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CountryPicker({
  value,
  onSelect,
  children,
  open,
  onOpenChange,
}: CountryPickerProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const searchInputRef = React.useRef<HTMLInputElement>(null);
  const searchInputId = React.useId();
  const countryListId = React.useId();
  const resultCountId = React.useId();
  const pickerOpen = open ?? uncontrolledOpen;
  const selectedCountry = getCountry(value);

  const matchingCountries = React.useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return COUNTRIES;

    return COUNTRIES.filter(
      (country) =>
        country.name.toLocaleLowerCase().includes(normalizedQuery) ||
        country.code.toLocaleLowerCase().includes(normalizedQuery),
    );
  }, [query]);

  const handleOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (open === undefined) setUncontrolledOpen(nextOpen);
      if (!nextOpen) setQuery("");
      onOpenChange?.(nextOpen);
    },
    [onOpenChange, open],
  );

  function handleSelect(code: string) {
    onSelect(code);
    handleOpenChange(false);
  }

  const trigger = children ?? (
    <Button type="button" variant="outline">
      <span aria-hidden="true">{selectedCountry?.flag ?? "🌍"}</span>
      <span>{selectedCountry?.name ?? "Choose country"}</span>
      <ChevronDown aria-hidden="true" />
    </Button>
  );

  return (
    <Popover open={pickerOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label="Choose your country"
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
            Search countries
          </label>
          <Input
            ref={searchInputRef}
            id={searchInputId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search countries..."
            autoComplete="off"
            aria-controls={countryListId}
            aria-describedby={resultCountId}
            className="pl-9"
          />
        </div>

        <p id={resultCountId} className="sr-only" aria-live="polite">
          {matchingCountries.length} {matchingCountries.length === 1 ? "country" : "countries"} available
        </p>

        <ul
          id={countryListId}
          aria-label="Countries"
          className="mt-2 max-h-72 space-y-0.5 overflow-y-auto pr-1"
        >
          {matchingCountries.map((country) => {
            const isSelected = country.code === selectedCountry?.code;

            return (
              <li key={country.code}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => handleSelect(country.code)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-sm px-2 py-2 text-left text-sm transition-colors duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    isSelected
                      ? "bg-accent text-accent-foreground"
                      : "hover:bg-accent/70 hover:text-accent-foreground",
                  )}
                >
                  <span className="text-base leading-none" aria-hidden="true">
                    {country.flag}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{country.name}</span>
                  {isSelected && (
                    <Check
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        {matchingCountries.length === 0 && (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">
            No countries match “{query.trim()}”.
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}

export default CountryPicker;
