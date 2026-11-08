"use client";

import type { ReactElement } from "react";
import {
  Fragment,
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { Check, Loader2, Search, X } from "lucide-react";

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
import { summarizeLocation } from "@/lib/location";
import { cn } from "@/lib/utils";

const OPTIONS_CHUNK_SIZE = 200;
const LETTER_GROUP_THRESHOLD = 60;
const LETTERS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ", "#"];

interface LetterGroup {
  letter: string;
  start: number;
  end: number;
}

const OptionRow = memo(function OptionRow({
  option,
  isSelected,
  isLocation,
  onToggle,
}: {
  option: string;
  isSelected: boolean;
  isLocation: boolean;
  onToggle: (option: string) => void;
}) {
  const location = isLocation ? summarizeLocation(option) : null;

  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={isSelected}
      onClick={() => onToggle(option)}
      className={cn(
        "flex min-w-0 items-start gap-2 rounded-sm px-2.5 py-2 text-left text-sm font-normal transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isSelected
          ? "bg-primary/10 text-foreground ring-1 ring-primary/30"
          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border",
          isSelected
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border bg-background text-transparent",
        )}
        aria-hidden="true"
      >
        <Check className="h-3 w-3" />
      </span>
      <span className="min-w-0 break-words" title={location?.full ?? option}>
        {location ? (
          <>{location.short}{location.hiddenCount > 0 && ` +${location.hiddenCount} more`}</>
        ) : option}
      </span>
    </button>
  );
});

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
  const [renderedCount, setRenderedCount] = useState(OPTIONS_CHUNK_SIZE);
  const [jumpRequest, setJumpRequest] = useState(0);
  const pendingJumpRef = useRef<string | null>(null);
  const [resultsContainer, setResultsContainer] = useState<HTMLDivElement | null>(null);
  const [loadMoreSentinel, setLoadMoreSentinel] = useState<HTMLDivElement | null>(null);
  const [draftValues, setDraftValues] = useState<Set<string>>(() =>
    valuesToSet(values),
  );
  const searchInputRef = useRef<HTMLInputElement>(null);
  const wasOpenRef = useRef(open);
  const titleId = useId();
  const descriptionId = useId();
  const searchId = useId();
  const resultsId = useId();
  const sectionId = useId();
  const labelText = label.trim().toLowerCase();
  const pluralLabel = labelText.endsWith("y")
    ? `${labelText.slice(0, -1)}ies`
    : `${labelText}s`;
  const trimmedQuery = query.trim();
  const showLetterGroups = query.length === 0 && options.length >= LETTER_GROUP_THRESHOLD;
  const { filteredOptions, groups, headingLetters } = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const matches = normalizedQuery
      ? options.filter((option) => option.toLowerCase().includes(normalizedQuery))
      : options;
    const groups: LetterGroup[] = [];
    const headingLetters = new Map<number, string>();
    if (query.length > 0 || options.length < LETTER_GROUP_THRESHOLD) {
      return { filteredOptions: matches, groups, headingLetters };
    }

    const buckets = new Map<string, string[]>();
    for (const option of matches) {
      const first = option
        .trim()
        .normalize("NFD")
        .replace(/\p{M}/gu, "")
        .charAt(0)
        .toUpperCase();
      const letter = /^[A-Z]$/.test(first) ? first : "#";
      const bucket = buckets.get(letter);
      if (bucket) bucket.push(option);
      else buckets.set(letter, [option]);
    }

    const filteredOptions: string[] = [];
    for (const letter of LETTERS) {
      const bucket = buckets.get(letter);
      if (!bucket) continue;
      const start = filteredOptions.length;
      filteredOptions.push(...bucket);
      groups.push({ letter, start, end: filteredOptions.length });
      headingLetters.set(start, letter);
    }
    return { filteredOptions, groups, headingLetters };
  }, [options, query]);
  const visibleOptions = filteredOptions.slice(0, renderedCount);
  const hasMore = renderedCount < filteredOptions.length;
  const selectedCount = draftValues.size;

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setQuery("");
      setDraftValues(valuesToSet(values));
      setRenderedCount(OPTIONS_CHUNK_SIZE);
      pendingJumpRef.current = null;
    }
    if (!open && wasOpenRef.current) {
      setQuery("");
      setRenderedCount(OPTIONS_CHUNK_SIZE);
      pendingJumpRef.current = null;
    }
    wasOpenRef.current = open;
  }, [open, values]);

  useEffect(() => {
    if (open && resultsContainer) resultsContainer.scrollTo({ top: 0 });
  }, [open, query, resultsContainer]);

  useEffect(() => {
    if (!open || isLoading || !hasMore || !resultsContainer || !loadMoreSentinel) return;

    let active = true;
    const observer = new IntersectionObserver((entries) => {
      if (active && entries.some((entry) => entry.isIntersecting)) {
        setRenderedCount((current) => Math.min(current + OPTIONS_CHUNK_SIZE, filteredOptions.length));
      }
    }, {
      root: resultsContainer,
      rootMargin: "0px 0px 600px 0px",
    });
    observer.observe(loadMoreSentinel);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [open, isLoading, hasMore, resultsContainer, loadMoreSentinel, renderedCount, filteredOptions.length]);

  useEffect(() => {
    const pendingJump = pendingJumpRef.current;
    if (!open || isLoading || !pendingJump || !resultsContainer) return;
    const heading = document.getElementById(`${sectionId}-${pendingJump}`);
    if (heading && resultsContainer.contains(heading)) {
      // Reset sticky positions so backward jumps use the heading's original location.
      resultsContainer.scrollTo({ top: 0 });
      heading.scrollIntoView({ block: "start" });
      pendingJumpRef.current = null;
    }
  }, [open, isLoading, jumpRequest, renderedCount, resultsContainer, sectionId]);

  function handleOpenChange(nextOpen: boolean) {
    setQuery("");
    setRenderedCount(OPTIONS_CHUNK_SIZE);
    pendingJumpRef.current = null;
    if (nextOpen) setDraftValues(valuesToSet(values));
    onOpenChange(nextOpen);
  }

  const toggleOption = useCallback((option: string) => {
    setDraftValues((current) => {
      const next = new Set(current);
      if (next.has(option)) {
        next.delete(option);
      } else {
        next.add(option);
      }
      return next;
    });
  }, []);

  function jumpToLetter(group: LetterGroup) {
    setRenderedCount((current) => Math.max(current, group.end + OPTIONS_CHUNK_SIZE));
    pendingJumpRef.current = group.letter;
    setJumpRequest((current) => current + 1);
  }

  function handleApply() {
    onApply(Array.from(draftValues));
    setQuery("");
    setRenderedCount(OPTIONS_CHUNK_SIZE);
    pendingJumpRef.current = null;
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
        <DialogHeader className="min-w-0 border-b border-border px-6 py-5">
          <DialogTitle id={titleId} className="px-8 font-serif text-xl sm:px-0 sm:pr-8 sm:text-2xl">
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
              onChange={(event) => {
                setQuery(event.target.value);
                setRenderedCount(OPTIONS_CHUNK_SIZE);
                pendingJumpRef.current = null;
              }}
              placeholder={`Search ${labelText}`}
              aria-controls={resultsId}
              className="pl-9"
            />
          </div>
          {showLetterGroups && (
            <nav aria-label="Jump to letter" className="flex min-w-0 gap-0.5 overflow-x-auto py-1">
              {LETTERS.map((letter) => {
                const group = groups.find((group) => group.letter === letter);
                return (
                  <button
                    key={letter}
                    type="button"
                    disabled={!group}
                    aria-label={`Jump to ${pluralLabel} starting with ${letter === "#" ? "a number or symbol" : letter}`}
                    onClick={() => {
                      if (group) jumpToLetter(group);
                    }}
                    className="flex h-9 w-8 shrink-0 items-center justify-center rounded-sm text-xs font-medium text-muted-foreground hover:bg-secondary/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-30 sm:h-7 sm:w-auto sm:min-w-0 sm:flex-1 sm:shrink"
                  >
                    {letter}
                  </button>
                );
              })}
            </nav>
          )}
          {selectedCount > 0 && (
            <div className="flex max-h-20 min-w-0 flex-wrap gap-1.5 overflow-y-auto">
              {Array.from(draftValues, (value) => (
                <span key={value} className="inline-flex max-w-full items-start gap-1 rounded-sm bg-secondary py-0.5 pr-0.5 pl-2 text-left text-sm">
                  <span className="min-w-0 break-words" title={value}>
                    {labelText === "location" ? summarizeLocation(value).short : value}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove ${value}`}
                    onClick={() => toggleOption(value)}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-background/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          )}
          {error && !isLoading && (
            <p role="status" className="text-sm text-muted-foreground">
              {error}
            </p>
          )}
        </DialogHeader>

        <div
          ref={setResultsContainer}
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
              <div className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
                {visibleOptions.map((option, index) => {
                  const letter = headingLetters.get(index);
                  return (
                    <Fragment key={option}>
                      {letter && (
                        <h3 id={`${sectionId}-${letter}`} className="eyebrow sticky -top-4 z-10 col-span-full bg-card px-2.5 py-2">
                          {letter}
                        </h3>
                      )}
                      <OptionRow
                        option={option}
                        isSelected={draftValues.has(option)}
                        isLocation={labelText === "location"}
                        onToggle={toggleOption}
                      />
                    </Fragment>
                  );
                })}
              </div>
              {hasMore && (
                <div ref={setLoadMoreSentinel} className="pt-4 text-center text-sm text-muted-foreground">
                  Showing <span className="tnum">{visibleOptions.length.toLocaleString("en-IN")}</span> of{" "}
                  <span className="tnum">{filteredOptions.length.toLocaleString("en-IN")}</span> {pluralLabel} — scroll for more
                </div>
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
