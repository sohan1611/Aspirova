"use client";

import {
  ArrowUpDown,
  Bookmark,
  ChevronDown,
  Loader2,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import FacetPicker from "@/components/FacetPicker";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import LocationScope from "@/components/LocationScope";
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
import { createSavedSearch, getFacets } from "@/lib/api";
import { getCountry } from "@/lib/countries";
import type { Facets, SavedSearchParams } from "@/lib/types";
import { useSession } from "@/lib/useSession";
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

const EXPERIENCE_OPTIONS = [
  { value: null, label: "All levels" },
  { value: "early", label: "Early career" },
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
  "experience",
  "remote",
  "location",
  "company",
  "top",
  "sort",
] as const;

const SAVED_SEARCH_PARAM_KEYS = [
  "q",
  "category",
  "kind",
  "remote",
  "scope",
  "country",
  "source",
  "experience",
] as const;

interface ActiveFilterDescriptor {
  id: string;
  label: React.ReactNode;
  humanLabel: string;
  onRemove: () => void;
}

interface SearchParamReader {
  get(name: string): string | null;
}

function getSavedSearchParams(searchParams: SearchParamReader): SavedSearchParams {
  const remote = searchParams.get("remote");

  return {
    q: searchParams.get("q") ?? undefined,
    category: searchParams.get("category") as SavedSearchParams["category"],
    kind: searchParams.get("kind") as SavedSearchParams["kind"],
    remote: remote === "true" ? true : remote === "false" ? false : undefined,
    scope: searchParams.get("scope") as SavedSearchParams["scope"],
    country: searchParams.get("country") ?? undefined,
    source: searchParams.get("source") as SavedSearchParams["source"],
    experience: searchParams.get("experience") as SavedSearchParams["experience"],
  };
}

function hasSavedSearchParams(searchParams: SearchParamReader): boolean {
  return SAVED_SEARCH_PARAM_KEYS.some((key) => {
    const value = searchParams.get(key);
    return value !== null && value !== "";
  });
}

function savedSearchNamePlaceholder(params: SavedSearchParams): string {
  const parts: string[] = [];
  const category = CATEGORY_OPTIONS.find((option) => option.value === params.category);
  const source = SOURCE_OPTIONS.find((option) => option.value === params.source);

  if (params.q) {
    const query = params.q.length > 36 ? `${params.q.slice(0, 36)}…` : params.q;
    parts.push(`“${query}”`);
  }
  if (category?.value) parts.push(category.label);
  else if (params.kind === "roles") parts.push("Roles");
  else if (params.kind === "competitions") parts.push("Competitions");
  if (params.remote === true) parts.push("Remote");
  if (params.remote === false) parts.push("On-site");
  if (params.country) {
    parts.push(getCountry(params.country)?.name ?? params.country.toUpperCase());
  } else if (params.scope === "abroad") {
    parts.push("Abroad");
  } else if (params.scope === "domestic") {
    parts.push("Domestic");
  }
  if (source?.value) parts.push(source.label);
  if (params.experience === "early") parts.push("Early career");

  return parts.join(" · ") || "My saved search";
}

function multiFacetButtonLabel(
  label: "company" | "location",
  values: string[],
): string {
  if (values.length === 0) return `Any ${label}`;
  if (values.length === 1) return values[0];
  return `${values.length} ${label === "company" ? "companies" : "locations"}`;
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
  const searchParams = useSearchParams();
  const session = useSession();
  const accessToken = session?.access_token;
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [facets, setFacets] = useState<Facets | null>(null);
  const [facetsStatus, setFacetsStatus] = useState<
    "idle" | "loading" | "loaded" | "error"
  >("idle");
  const [facetError, setFacetError] = useState<string | null>(null);
  const [locationPickerOpen, setLocationPickerOpen] = useState(false);
  const [companyPickerOpen, setCompanyPickerOpen] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveAlertsEnabled, setSaveAlertsEnabled] = useState(true);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSavingSearch, setIsSavingSearch] = useState(false);

  // Resync the search input to the URL when params change externally (Clear all / Back),
  // without remounting — so the Filter popover stays open across selections.
  // React's "adjust state during render" pattern (guarded), not an effect.
  const paramsSignature = searchParams.toString();
  const [syncedSignature, setSyncedSignature] = useState(paramsSignature);
  if (paramsSignature !== syncedSignature) {
    setSyncedSignature(paramsSignature);
    setQ(searchParams.get("q") ?? "");
  }

  const top = searchParams.get("top");
  const selectedLocations = searchParams
    .getAll("location")
    .map((value) => value.trim())
    .filter(Boolean);
  const selectedCompanies = searchParams
    .getAll("company")
    .map((value) => value.trim())
    .filter(Boolean);
  const sort =
    searchParams.get("sort") === "deadline"
      ? "deadline"
      : searchParams.get("sort") === "recent"
        ? "recent"
        : "student";
  const activeFilters: ActiveFilterDescriptor[] = FILTER_KEYS.flatMap(
    (key): ActiveFilterDescriptor[] => {
      if (key === "company" || key === "location") {
        const values = searchParams
          .getAll(key)
          .map((value) => value.trim())
          .filter(Boolean);

        return values.map((value, index) => ({
          id: `${key}:${index}:${value}`,
          label: value,
          humanLabel: `${key === "company" ? "Company" : "Location"}: ${value}`,
          onRemove: () =>
            commitMultiParam(
              key,
              values.filter((_currentValue, currentIndex) => currentIndex !== index),
            ),
        }));
      }

      const value = searchParams.get(key);
      if (value === null) return [];
      if (key === "sort" && value !== "recent" && value !== "deadline") return [];

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
      } else if (key === "experience") {
        humanLabel =
          EXPERIENCE_OPTIONS.find((option) => option.value === value)?.label ?? value;
        label = humanLabel;
      } else if (key === "remote") {
        humanLabel =
          REMOTE_OPTIONS.find((option) => option.value === value)?.label ?? value;
        label = humanLabel;
      } else if (key === "top") {
        const topLabel =
          TOP_OPTIONS.find((option) => option.value === value)?.label ?? value;
        humanLabel = `Top ${topLabel}`;
        label = (
          <>
            Top <span className="tnum">{topLabel}</span>
          </>
        );
      } else if (key === "sort") {
        humanLabel = value === "deadline" ? "Closing soon" : "Newest";
        label = humanLabel;
      }

      return [{ id: key, label, humanLabel, onRemove: () => updateParam(key, null) }];
    },
  );
  const activeFilterCount = activeFilters.length;
  const hasFilters = activeFilterCount > 0;
  const savedSearchParams = getSavedSearchParams(searchParams);
  const canSaveSearch = hasSavedSearchParams(searchParams);
  const saveSearchPlaceholder = savedSearchNamePlaceholder(savedSearchParams);

  function updateParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    params.delete("page");
    const query = params.toString();
    navigate(query ? `/?${query}` : "/");
  }

  function commitMultiParam(key: "company" | "location", values: string[]) {
    const params = new URLSearchParams(searchParams.toString());
    params.delete(key);
    for (const value of values) {
      const nextValue = value.trim();
      if (nextValue) params.append(key, nextValue);
    }
    params.delete("page");
    const query = params.toString();
    navigate(query ? `/?${query}` : "/");
  }

  function loadFacetsIfNeeded() {
    if (facetsStatus === "loading" || facetsStatus === "loaded") return;

    setFacetsStatus("loading");
    setFacetError(null);
    void getFacets()
      .then((nextFacets) => {
        setFacets(nextFacets);
        setFacetsStatus("loaded");
      })
      .catch(() => {
        setFacets({ companies: [], locations: [] });
        setFacetsStatus("error");
        setFacetError("Could not load the live list. Reopen to retry.");
      });
  }

  function handleLocationPickerOpenChange(open: boolean) {
    setLocationPickerOpen(open);
    if (open) loadFacetsIfNeeded();
  }

  function handleCompanyPickerOpenChange(open: boolean) {
    setCompanyPickerOpen(open);
    if (open) loadFacetsIfNeeded();
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    updateParam("q", q || null);
  }

  function clearFilters() {
    navigate("/");
  }

  function handleSaveDialogOpenChange(open: boolean) {
    setSaveDialogOpen(open);
    if (open) {
      setSaveName("");
      setSaveAlertsEnabled(true);
      setSaveError(null);
    }
  }

  async function handleSaveSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || isSavingSearch) return;

    setIsSavingSearch(true);
    setSaveError(null);
    try {
      await createSavedSearch(accessToken, {
        name: saveName.trim() || null,
        params: savedSearchParams,
        alerts_enabled: saveAlertsEnabled,
      });
      toast.success("Search saved");
      setSaveDialogOpen(false);
    } catch {
      setSaveError("We couldn't save this search. Please try again.");
    } finally {
      setIsSavingSearch(false);
    }
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <form
          onSubmit={handleSubmit}
          className="flex min-w-0 w-full flex-wrap gap-x-2 gap-y-2 sm:w-auto"
        >
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

        <div className="ml-auto flex w-full min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-2 sm:w-auto sm:flex-nowrap">
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
                  <Label htmlFor="filter-experience" className="eyebrow">
                    Experience
                  </Label>
                  <Select
                    value={searchParams.get("experience") ?? "all"}
                    disabled={isPending}
                    onValueChange={(value) =>
                      updateParam("experience", value === "all" ? null : value)
                    }
                  >
                    <SelectTrigger id="filter-experience" aria-label="Experience">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EXPERIENCE_OPTIONS.map((option) => (
                        <SelectItem key={option.label} value={option.value ?? "all"}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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

                <div className="space-y-2">
                  <p className="eyebrow">Location</p>
                  <FacetPicker
                    label="location"
                    options={facets?.locations ?? []}
                    values={selectedLocations}
                    open={locationPickerOpen}
                    onOpenChange={handleLocationPickerOpenChange}
                    onApply={(next) => commitMultiParam("location", next)}
                    isLoading={facetsStatus === "loading"}
                    error={facetError}
                    trigger={
                      <Button
                        type="button"
                        variant="outline"
                        disabled={isPending}
                        aria-label="Choose location filter"
                        className="w-full justify-between"
                      >
                        <span className="min-w-0 truncate text-left">
                          {multiFacetButtonLabel("location", selectedLocations)}
                        </span>
                        <ChevronDown
                          className="h-4 w-4 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      </Button>
                    }
                  />
                </div>

                <div className="space-y-2">
                  <p className="eyebrow">Company</p>
                  <FacetPicker
                    label="company"
                    options={facets?.companies ?? []}
                    values={selectedCompanies}
                    open={companyPickerOpen}
                    onOpenChange={handleCompanyPickerOpenChange}
                    onApply={(next) => commitMultiParam("company", next)}
                    isLoading={facetsStatus === "loading"}
                    error={facetError}
                    trigger={
                      <Button
                        type="button"
                        variant="outline"
                        disabled={isPending}
                        aria-label="Choose company filter"
                        className="w-full justify-between"
                      >
                        <span className="min-w-0 truncate text-left">
                          {multiFacetButtonLabel("company", selectedCompanies)}
                        </span>
                        <ChevronDown
                          className="h-4 w-4 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      </Button>
                    }
                  />
                </div>

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

          {accessToken && canSaveSearch && (
            <Dialog open={saveDialogOpen} onOpenChange={handleSaveDialogOpenChange}>
              <DialogTrigger asChild>
                <Button type="button" variant="outline" size="sm" disabled={isPending}>
                  <Bookmark aria-hidden="true" />
                  Save search
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-md">
                <form onSubmit={handleSaveSearch} className="grid gap-5">
                  <DialogHeader>
                    <DialogTitle className="font-serif text-2xl">Save this search</DialogTitle>
                    <DialogDescription>
                      Save these filters so you can return to the same opportunities anytime.
                    </DialogDescription>
                  </DialogHeader>

                  <div className="grid gap-2.5">
                    <Label className="eyebrow" htmlFor="saved-search-name">
                      Name <span className="normal-case text-muted-foreground">(optional)</span>
                    </Label>
                    <Input
                      id="saved-search-name"
                      value={saveName}
                      maxLength={80}
                      disabled={isSavingSearch}
                      onChange={(event) => setSaveName(event.target.value)}
                      placeholder={saveSearchPlaceholder}
                    />
                  </div>

                  <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/40 px-3 py-3">
                    <input
                      id="saved-search-alerts"
                      type="checkbox"
                      checked={saveAlertsEnabled}
                      disabled={isSavingSearch}
                      onChange={(event) => setSaveAlertsEnabled(event.target.checked)}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-border bg-background accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                    />
                    <div className="min-w-0">
                      <Label htmlFor="saved-search-alerts" className="cursor-pointer">
                        Email alerts
                      </Label>
                      <p className="mt-0.5 text-sm text-muted-foreground">
                        We&apos;ll be able to email you new matches.
                      </p>
                    </div>
                  </div>

                  {saveError && (
                    <p id="saved-search-error" role="alert" className="text-sm text-destructive">
                      {saveError}
                    </p>
                  )}

                  <DialogFooter>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={isSavingSearch}
                      onClick={() => setSaveDialogOpen(false)}
                    >
                      Cancel
                    </Button>
                    <Button type="submit" disabled={isSavingSearch}>
                      {isSavingSearch ? "Saving…" : "Save search"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          )}

          <LocationScope />

          <Select
            value={sort}
            disabled={isPending}
            onValueChange={(value) =>
              updateParam("sort", value === "student" ? null : value)
            }
          >
            <SelectTrigger aria-label="Sort opportunities">
              <ArrowUpDown aria-hidden="true" />
              <SelectValue>
                {sort === "deadline"
                  ? "Closing soon"
                  : sort === "recent"
                    ? "Newest"
                    : "For students"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="student">For students</SelectItem>
              <SelectItem value="recent">Newest</SelectItem>
              <SelectItem value="deadline">Closing soon</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {hasFilters && (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {activeFilters.map(({ id, label, humanLabel, onRemove }) => (
            <Badge
              key={id}
              variant="secondary"
              className="max-w-full gap-1 py-0.5 pr-0.5 pl-2 text-sm font-medium tracking-normal normal-case"
            >
              <span className="min-w-0 truncate">{label}</span>
              <button
                type="button"
                aria-label={`Remove ${humanLabel} filter`}
                disabled={isPending}
                onClick={onRemove}
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
