"use client";

import { ArrowUpDown, Loader2, Search, SlidersHorizontal, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const CATEGORY_OPTIONS = [
  { value: null, label: "All" },
  { value: "internship", label: "Internships" },
  { value: "job", label: "Jobs" },
  { value: "hackathon", label: "Hackathons" },
  { value: "competition", label: "Competitions" },
];

const SOURCE_OPTIONS = [
  { value: null, label: "All" },
  { value: "direct", label: "Direct from company" },
  { value: "unstop", label: "Unstop" },
  { value: "remoteok", label: "RemoteOK" },
  { value: "devpost", label: "Devpost" },
];

const REMOTE_OPTIONS = [
  { value: null, label: "Any" },
  { value: "true", label: "Remote" },
  { value: "false", label: "On-site" },
];

const TOP_OPTIONS = [
  { value: null, label: "Any" },
  { value: "10", label: "10" },
  { value: "50", label: "50" },
  { value: "100", label: "100" },
  { value: "500", label: "500" },
  { value: "1000", label: "1000" },
];

const FILTER_KEYS = [
  "q",
  "category",
  "source",
  "remote",
  "location",
  "company",
  "top",
] as const;

interface ActiveFilterDescriptor {
  key: (typeof FILTER_KEYS)[number];
  label: React.ReactNode;
  humanLabel: string;
}

function SegmentedGroup({
  label,
  options,
  active,
  onSelect,
  disabled = false,
}: {
  label: string;
  options: { value: string | null; label: string }[];
  active: string | null;
  onSelect: (value: string | null) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex max-w-full flex-wrap rounded-md border border-border bg-muted p-1"
    >
      {options.map((option) => {
        const isActive = option.value === active;
        return (
          <button
            key={option.label}
            type="button"
            aria-pressed={isActive}
            disabled={disabled}
            onClick={() => onSelect(option.value)}
            className={cn(
              "whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] disabled:cursor-wait",
              isActive
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default function SearchFilters() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [location, setLocation] = useState(searchParams.get("location") ?? "");
  const [company, setCompany] = useState(searchParams.get("company") ?? "");

  // Resync inputs to the URL when params change externally (Clear all / Back),
  // without remounting — so the Filter popover stays open across selections.
  // React's "adjust state during render" pattern (guarded), not an effect.
  const paramsSignature = searchParams.toString();
  const [syncedSignature, setSyncedSignature] = useState(paramsSignature);
  if (paramsSignature !== syncedSignature) {
    setSyncedSignature(paramsSignature);
    setQ(searchParams.get("q") ?? "");
    setLocation(searchParams.get("location") ?? "");
    setCompany(searchParams.get("company") ?? "");
  }

  const top = searchParams.get("top");
  const sort = searchParams.get("sort") === "deadline" ? "deadline" : "recent";
  const activeFilters: ActiveFilterDescriptor[] = FILTER_KEYS.flatMap((key) => {
    const value = searchParams.get(key);
    if (value === null) return [];

    let humanLabel = value;
    let label: React.ReactNode = value;

    if (key === "q") {
      humanLabel = `Search: "${value}"`;
      label = humanLabel;
    } else if (key === "category") {
      humanLabel =
        CATEGORY_OPTIONS.find((option) => option.value === value)?.label ?? value;
      label = humanLabel;
    } else if (key === "source") {
      humanLabel =
        SOURCE_OPTIONS.find((option) => option.value === value)?.label ?? value;
      label = humanLabel;
    } else if (key === "remote") {
      humanLabel =
        REMOTE_OPTIONS.find((option) => option.value === value)?.label ?? value;
      label = humanLabel;
    } else if (key === "top") {
      const topLabel = TOP_OPTIONS.find((option) => option.value === value)?.label ?? value;
      humanLabel = `Top ${topLabel}`;
      label = (
        <>
          Top <span className="tnum">{topLabel}</span>
        </>
      );
    }

    return [{ key, label, humanLabel }];
  });
  const activeFilterCount = activeFilters.length;
  const hasFilters = activeFilterCount > 0;

  function updateParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    params.delete("page");
    startTransition(() => {
      router.push(`/?${params.toString()}`);
    });
  }

  function commitTextParam(key: string, value: string) {
    const nextValue = value.trim() || null;
    if ((searchParams.get(key) ?? "") === (nextValue ?? "")) return;
    updateParam(key, nextValue);
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    updateParam("q", q || null);
  }

  function handleLocationSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    commitTextParam("location", location);
  }

  function handleCompanySubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    commitTextParam("company", company);
  }

  function clearFilters() {
    const params = new URLSearchParams();
    const currentSort = searchParams.get("sort");
    if (currentSort) params.set("sort", currentSort);
    startTransition(() => {
      router.push(`/?${params.toString()}`);
    });
  }

  return (
    <div
      aria-busy={isPending}
      className={cn(
        "flex flex-col gap-3",
        isPending && "pointer-events-none cursor-progress",
      )}
    >
      {isPending && (
        <span className="sr-only" role="status">
          Updating opportunities…
        </span>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <form onSubmit={handleSubmit} className="flex w-full flex-wrap gap-2 sm:w-auto">
          <div className="relative min-w-0 flex-1 sm:flex-none">
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              aria-label="Search opportunities"
              placeholder="Search opportunities..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="w-full pl-9 sm:w-72"
            />
          </div>
          <Button type="submit" disabled={isPending}>
            Search
          </Button>
        </form>

        <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto sm:flex-nowrap">
          <Popover>
            <PopoverTrigger asChild>
              <Button type="button" variant="outline" disabled={isPending}>
                {isPending ? (
                  <Loader2
                    className="animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                ) : (
                  <SlidersHorizontal aria-hidden="true" />
                )}
                Filter
                {hasFilters && (
                  <Badge
                    variant="secondary"
                    className="tnum"
                    aria-label={`${activeFilterCount} active filters`}
                  >
                    {activeFilterCount}
                  </Badge>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              aria-busy={isPending}
              className={cn(
                "max-h-(--radix-popover-content-available-height) overflow-y-auto",
                isPending && "pointer-events-none",
              )}
            >
              <div className="space-y-5">
                <div className="space-y-2">
                  <p className="eyebrow">Category</p>
                  <SegmentedGroup
                    label="Category"
                    options={CATEGORY_OPTIONS}
                    active={searchParams.get("category")}
                    onSelect={(value) => updateParam("category", value)}
                    disabled={isPending}
                  />
                </div>

                <div className="space-y-2">
                  <p className="eyebrow">Source</p>
                  <SegmentedGroup
                    label="Source"
                    options={SOURCE_OPTIONS}
                    active={searchParams.get("source")}
                    onSelect={(value) => updateParam("source", value)}
                    disabled={isPending}
                  />
                </div>

                <div className="space-y-2">
                  <p className="eyebrow">Work mode</p>
                  <SegmentedGroup
                    label="Work mode"
                    options={REMOTE_OPTIONS}
                    active={searchParams.get("remote")}
                    onSelect={(value) => updateParam("remote", value)}
                    disabled={isPending}
                  />
                </div>

                <form onSubmit={handleLocationSubmit} className="space-y-2">
                  <Label htmlFor="filter-location" className="eyebrow">
                    Location
                  </Label>
                  <Input
                    id="filter-location"
                    aria-label="Location"
                    placeholder="City, country…"
                    value={location}
                    onBlur={() => commitTextParam("location", location)}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </form>

                <form onSubmit={handleCompanySubmit} className="space-y-2">
                  <Label htmlFor="filter-company" className="eyebrow">
                    Company
                  </Label>
                  <Input
                    id="filter-company"
                    aria-label="Company"
                    placeholder="Company name…"
                    value={company}
                    onBlur={() => commitTextParam("company", company)}
                    onChange={(e) => setCompany(e.target.value)}
                  />
                </form>

                <div className="space-y-2">
                  <p className="eyebrow">Top companies</p>
                  <SegmentedGroup
                    label="Top companies"
                    options={TOP_OPTIONS}
                    active={TOP_OPTIONS.some((option) => option.value === top) ? top : null}
                    onSelect={(value) => updateParam("top", value)}
                    disabled={isPending}
                  />
                </div>

                {hasFilters && (
                  <>
                    <Separator />
                    <div className="flex justify-end">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={isPending}
                        onClick={clearFilters}
                      >
                        Clear all
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </PopoverContent>
          </Popover>

          <Select
            value={sort}
            disabled={isPending}
            onValueChange={(value) =>
              updateParam("sort", value === "recent" ? null : "deadline")
            }
          >
            <SelectTrigger aria-label="Sort opportunities">
              <ArrowUpDown aria-hidden="true" />
              <SelectValue>{sort === "deadline" ? "Closing soon" : "Newest"}</SelectValue>
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="recent">Newest</SelectItem>
              <SelectItem value="deadline">Closing soon</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {hasFilters && (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {activeFilters.map(({ key, label, humanLabel }) => (
            <Badge
              key={key}
              variant="secondary"
              className="max-w-full gap-1 py-0.5 pr-0.5 pl-2 text-sm font-medium tracking-normal normal-case"
            >
              <span className="min-w-0 truncate">{label}</span>
              <button
                type="button"
                aria-label={`Remove ${humanLabel} filter`}
                disabled={isPending}
                onClick={() => updateParam(key, null)}
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-[color,background-color,box-shadow] duration-200 ease-[var(--ease-premium)] hover:bg-background/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </Badge>
          ))}
          <button
            type="button"
            disabled={isPending}
            onClick={clearFilters}
            className="min-h-7 whitespace-nowrap rounded-sm px-1.5 py-1 text-sm font-medium text-muted-foreground transition-colors duration-200 ease-[var(--ease-premium)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  );
}
