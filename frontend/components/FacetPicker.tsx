"use client";

import type { ReactElement } from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
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
  values: string[];
  onApply: (next: string[]) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactElement;
  isLoading?: boolean;
  error?: string | null;
}

function valuesToSet(values: string[]) {
  return new Set(values.map((value) => value.trim()).filter(Boolean));
}

export default function FacetPicker({
  label,
  options,
  values,
  onApply,
  open,
  onOpenChange,
  trigger,
  isLoading = false,
  error = null,
}: FacetPickerProps) {
  const [query, setQuery] = useState("");
  const [draftValues, setDraftValues] = useState<Set<string>>(() =>
    valuesToSet(values),
  );
  const searchInputRef = useRef<HTMLInputElement>(null);
  const wasOpenRef = useRef(open);
  const titleId = useId();
  const descriptionId = useId();
  const searchId = useId();
  const resultsId = useId();
  const labelText = label.trim().toLowerCase();
  const pluralLabel = labelText.endsWith("y")
    ? `${labelText.slice(0, -1)}ies`
    : `${labelText}s`;
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
  const selectedCount = draftValues.size;

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setQuery("");
      setDraftValues(valuesToSet(values));
    }
    if (!open && wasOpenRef.current) setQuery("");
    wasOpenRef.current = open;
  }, [open, values]);

  function handleOpenChange(nextOpen: boolean) {
    setQuery("");
    if (nextOpen) setDraftValues(valuesToSet(values));
    onOpenChange(nextOpen);
  }

  function toggleOption(option: string) {
    setDraftValues((current) => {
      const next = new Set(current);
      if (next.has(option)) {
        next.delete(option);
      } else {
        next.add(option);
      }
      return next;
    });
  }

  function handleApply() {
    onApply(Array.from(draftValues));
    setQuery("");
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        className="gap-0 overflow-hidden p-0 sm:max-w-3xl"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchInputRef.current?.focus();
        }}
      >
        <DialogHeader className="border-b border-border px-6 py-5">
          <DialogTitle id={titleId} className="font-serif text-2xl">
            Choose {pluralLabel}
          </DialogTitle>
          <DialogDescription id={descriptionId} className="sr-only">
            Search and select one or more {pluralLabel}.
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
          {selectedCount > 0 && (
            <p className="text-sm text-muted-foreground">
              {selectedCount} selected
            </p>
          )}
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
                  const isSelected = draftValues.has(option);
                  return (
                    <button
                      key={option}
                      type="button"
                      role="checkbox"
                      aria-checked={isSelected}
                      onClick={() => toggleOption(option)}
                      className={cn(
                        "flex min-w-0 items-center gap-2 rounded-sm px-2.5 py-2 text-left text-sm font-normal transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        isSelected
                          ? "bg-primary/10 text-foreground ring-1 ring-primary/30"
                          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                      )}
                    >
                      <span
                        className={cn(
                          "flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border",
                          isSelected
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-background text-transparent",
                        )}
                        aria-hidden="true"
                      >
                        <Check className="h-3 w-3" />
                      </span>
                      <span className="min-w-0 truncate">{option}</span>
                    </button>
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

        <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-3">
          <Button
            type="button"
            variant="ghost"
            disabled={selectedCount === 0}
            onClick={() => setDraftValues(new Set())}
          >
            Clear all
          </Button>
          <Button type="button" onClick={handleApply}>
            {selectedCount > 0 ? `Apply (${selectedCount})` : "Apply"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
