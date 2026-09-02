"use client";

import { Loader2, SlidersHorizontal } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { CountedFilterOption } from "@/components/CountedFilterControls";
import { cn } from "@/lib/utils";

export type CountedFacetsStatus = "loading" | "loaded" | "error";

export interface SearchParamReader {
  get(name: string): string | null;
  getAll(name: string): string[];
  toString(): string;
}

export function activeValues(searchParams: SearchParamReader, key: string): string[] {
  return Array.from(
    new Set(
      searchParams
        .getAll(key)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  );
}

export function activeSingleValue(
  searchParams: SearchParamReader,
  key: string,
): string | null {
  const value = searchParams.get(key)?.trim();
  return value || null;
}

export function countedOptions(
  options: CountedFilterOption[] | undefined,
): CountedFilterOption[] {
  return (options ?? []).filter((option) => option.count > 0);
}

export function humanizeValue(value: string): string {
  return value
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function optionLabel(
  options: CountedFilterOption[] | undefined,
  value: string,
): string {
  return options?.find((option) => option.value === value)?.label ?? humanizeValue(value);
}

export function setRepeatedParam(params: URLSearchParams, key: string, values: string[]) {
  params.delete(key);
  for (const value of values) {
    const nextValue = value.trim();
    if (nextValue) params.append(key, nextValue);
  }
}

export function countedStatusLabel(status: CountedFacetsStatus): string {
  if (status === "loading") return "Loading counts...";
  if (status === "error") return "Counts unavailable";
  return "No counted options available";
}

// `...triggerProps` is load-bearing, not tidiness. This renders inside
// <PopoverTrigger asChild> / <SheetTrigger asChild>, and Radix opens the panel by
// cloning this child to inject onClick, aria-expanded, data-state and a ref.
function FilterTriggerButton({
  activeFilterCount,
  activeFilterLabel,
  isPending,
  ...triggerProps
}: React.ComponentProps<typeof Button> & {
  activeFilterCount: number;
  activeFilterLabel: string;
  isPending: boolean;
}) {
  const hasFilters = activeFilterCount > 0;

  return (
    <Button
      {...triggerProps}
      type="button"
      variant="outline"
      size="sm"
      disabled={isPending}
      aria-label={
        hasFilters ? `Filters, ${activeFilterCount} active ${activeFilterLabel}` : "Filters"
      }
    >
      {isPending ? (
        <Loader2
          className="animate-spin motion-reduce:animate-none"
          aria-hidden="true"
        />
      ) : (
        <SlidersHorizontal aria-hidden="true" />
      )}
      Filters
      {hasFilters && (
        <Badge
          variant="secondary"
          className="tnum"
          aria-label={`${activeFilterCount} active ${activeFilterLabel}`}
        >
          {activeFilterCount}
        </Badge>
      )}
    </Button>
  );
}

export function CountedAdvancedFilterShell({
  activeFilterCount,
  activeFilterLabel,
  isPending,
  panelLabel,
  mobileDescription,
  idPrefixBase,
  children,
}: {
  activeFilterCount: number;
  activeFilterLabel: string;
  isPending: boolean;
  panelLabel: string;
  mobileDescription: string;
  idPrefixBase: string;
  children: (props: { idPrefix: string; onClose?: () => void }) => ReactNode;
}) {
  const [desktopOpen, setDesktopOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      <span className="sr-only" role="status" aria-live="polite">
        {activeFilterCount === 0
          ? `No active ${activeFilterLabel}`
          : `${activeFilterCount} active ${activeFilterLabel}`}
      </span>

      <div className="hidden md:block">
        <Popover modal open={desktopOpen} onOpenChange={setDesktopOpen}>
          <PopoverTrigger asChild>
            <FilterTriggerButton
              activeFilterCount={activeFilterCount}
              activeFilterLabel={activeFilterLabel}
              isPending={isPending}
            />
          </PopoverTrigger>
          <PopoverContent
            align="end"
            aria-label={panelLabel}
            className={cn(
              "max-h-(--radix-popover-content-available-height) w-[min(26rem,calc(100vw-2rem))] overflow-y-auto p-0",
              isPending && "pointer-events-none",
            )}
          >
            {children({ idPrefix: `desktop-${idPrefixBase}` })}
          </PopoverContent>
        </Popover>
      </div>

      <div className="md:hidden">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <FilterTriggerButton
              activeFilterCount={activeFilterCount}
              activeFilterLabel={activeFilterLabel}
              isPending={isPending}
            />
          </SheetTrigger>
          <SheetContent
            side="bottom"
            className="max-h-[85vh] rounded-t-md border-border p-0"
          >
            <SheetHeader className="border-b border-border pr-12">
              <SheetTitle className="font-serif text-2xl">Filters</SheetTitle>
              <SheetDescription>{mobileDescription}</SheetDescription>
            </SheetHeader>
            <div className="min-h-0 overflow-y-auto">
              {children({
                idPrefix: `mobile-${idPrefixBase}`,
                onClose: () => setMobileOpen(false),
              })}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
