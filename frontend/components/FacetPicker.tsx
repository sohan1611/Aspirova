"use client";

import type { ReactElement } from "react";
import { useId, useMemo, useRef, useState } from "react";
import { Check, Loader2, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const MAX_RENDERED_OPTIONS = 240;

interface FacetPickerProps {
  label: string;
  options: string[];
  value: string | null;
  onSelect: (value: string | null) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactElement;
  isLoading?: boolean;
  error?: string | null;
}

export default function FacetPicker({
  label,
  options,
  value,
  onSelect,
  open,
  onOpenChange,
  trigger,
  isLoading = false,
  error = null,
}: FacetPickerProps) {
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const searchId = useId();
  const resultsId = useId();
  const labelText = label.trim().toLowerCase();
  const trimmedQuery = query.trim();
  const normalizedQuery = trimmedQuery.toLowerCase();
  const filteredOptions = useMemo(() => {
    if (!normalizedQuery) return options;
    return options.filter((option) =>
      option.toLowerCase().includes(normalizedQuery),
    );
  }, [normalizedQuery, options]);
  const visibleOptions = filteredOptions.slice(0, MAX_RENDERED_OPTIONS);
  const isTruncated = filteredOptions.length > MAX_RENDERED_OPTIONS;

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) setQuery("");
    onOpenChange(nextOpen);
  }

  function handleSelect(nextValue: string | null) {
    onSelect(nextValue);
    setQuery("");
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        className="gap-0 p-0 sm:max-w-3xl"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchInputRef.current?.focus();
        }}
      >
        <DialogHeader className="border-b border-border px-6 py-5">
          <DialogTitle id={titleId} className="font-serif text-2xl">
            Choose {labelText}
          </DialogTitle>
          <DialogDescription id={descriptionId} className="sr-only">
            Search and select one {labelText} filter value.
          </DialogDescription>
          <div className="relative">
            <Label htmlFor={searchId} className="sr-only">
              Search {labelText}
            </Label>
            <Search
              className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              ref={searchInputRef}
              id={searchId}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${labelText}`}
              aria-controls={resultsId}
              className="pl-9"
            />
          </div>
          {error && !isLoading && (
            <p role="status" className="text-sm text-muted-foreground">
              {error}
            </p>
          )}
        </DialogHeader>

        <div
          id={resultsId}
          aria-busy={isLoading}
          className="max-h-[min(60vh,28rem)] overflow-y-auto px-6 py-4"
        >
          <div className="sticky top-0 z-10 bg-background pb-3">
            <Button
              type="button"
              variant={value === null ? "secondary" : "outline"}
              aria-pressed={value === null}
              onClick={() => handleSelect(null)}
              className="w-full justify-start"
            >
              Any {labelText}
            </Button>
          </div>

          {isLoading ? (
            <div className="flex min-h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              Loading {labelText} list...
            </div>
          ) : filteredOptions.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {trimmedQuery
                ? `No ${labelText} matches "${trimmedQuery}"`
                : `No ${labelText} values available.`}
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3 lg:grid-cols-4">
                {visibleOptions.map((option) => {
                  const isSelected = option === value;
                  return (
                    <Button
                      key={option}
                      type="button"
                      variant="ghost"
                      aria-pressed={isSelected}
                      onClick={() => handleSelect(option)}
                      className={cn(
                        "min-w-0 justify-between px-2.5 text-left font-normal",
                        isSelected
                          ? "bg-primary/10 text-foreground ring-1 ring-primary/30"
                          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                      )}
                    >
                      <span className="min-w-0 truncate">{option}</span>
                      {isSelected && (
                        <Check className="h-4 w-4 shrink-0" aria-hidden="true" />
                      )}
                    </Button>
                  );
                })}
              </div>
              {isTruncated && (
                <p className="pt-4 text-center text-sm text-muted-foreground">
                  Keep typing to narrow...
                </p>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
