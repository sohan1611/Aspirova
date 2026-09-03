"use client";

import { ArrowUpDown, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ListingSearchInput from "@/components/ListingSearchInput";
import {
  activeSingleValue,
  activeValues,
  countedStatusLabel,
  CountedAdvancedFilterShell,
  optionLabel,
  setRepeatedParam,
  type CountedFacetsStatus,
  type SearchParamReader,
} from "@/components/CountedAdvancedFilterShell";
import {
  ActiveFilterChips,
  CountedMultiSelectGroup,
  CountedSingleSelectGroup,
  FilterPanelSection,
  type ActiveFilterChip,
} from "@/components/CountedFilterControls";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { getFacets, type FeedParams } from "@/lib/api";
import {
  applyOpportunityListingLocation,
  clearOpportunityListingFilters,
  defaultOpportunityListingLocationOptions,
  getOpportunityListingLocation,
  loadOpportunityListingControlCounts,
  opportunityListingHref,
  OPPORTUNITY_EXPERIENCE_OPTIONS,
  type OpportunityListingCountedFilters,
  type OpportunityListingLocation,
  type OpportunityListingPath,
  type OpportunityListingSort,
} from "@/lib/opportunityListingQuery";
import type { Facets } from "@/lib/types";
import { cn } from "@/lib/utils";

export type OpportunityListingFacetsStatus = CountedFacetsStatus;

export interface OpportunityListingFacetsData extends OpportunityListingCountedFilters {
  facets: Facets;
}

export interface OpportunityListingFacetsState {
  data: OpportunityListingFacetsData | null;
  facetsStatus: OpportunityListingFacetsStatus;
}

type AdvancedFilterKey = "company" | "source" | "experience";

const SOURCE_FILTER_OPTIONS = [
  { value: "direct", label: "Direct" },
  { value: "unstop", label: "Unstop" },
  { value: "remoteok", label: "RemoteOK" },
  { value: "devpost", label: "Devpost" },
] as const;
const SORT_OPTIONS: Array<{ value: OpportunityListingSort; label: string }> = [
  { value: "student", label: "For students" },
  { value: "recent", label: "Newest" },
  { value: "deadline", label: "Closing soon" },
];
const FACET_CATEGORY_VALUES = new Set(["internship", "job", "hackathon", "competition"]);

const listingFacetsCache = new Map<string, OpportunityListingFacetsData>();
const listingFacetsPromises = new Map<string, Promise<OpportunityListingFacetsData>>();

function cacheKeyFor(baseQuery: FeedParams): string {
  const params = new URLSearchParams();
  if (baseQuery.category) params.set("category", baseQuery.category);
  if (baseQuery.kind) params.set("kind", baseQuery.kind);
  if (baseQuery.remote !== undefined) params.set("remote", String(baseQuery.remote));
  return params.toString();
}

function emptyFacets(): Facets {
  return { companies: [], locations: [], company_counts: [], location_counts: [] };
}

function getFacetRequest(baseQuery: FeedParams) {
  return {
    category:
      baseQuery.category && FACET_CATEGORY_VALUES.has(baseQuery.category)
        ? baseQuery.category
        : undefined,
    kind: baseQuery.kind,
  };
}

function loadOpportunityListingFacetsOnce(
  baseQuery: FeedParams,
): Promise<OpportunityListingFacetsData> {
  const key = cacheKeyFor(baseQuery);
  const cached = listingFacetsCache.get(key);
  if (cached) return Promise.resolve(cached);

  const existing = listingFacetsPromises.get(key);
  if (existing) return existing;

  const promise = Promise.all([
    getFacets(getFacetRequest(baseQuery)),
    loadOpportunityListingControlCounts(baseQuery),
  ]).then(([facets, counts]) => {
    const data = { facets, ...counts };
    listingFacetsCache.set(key, data);
    return data;
  });
  listingFacetsPromises.set(key, promise);
  return promise;
}

export function useOpportunityListingFacets(
  baseQuery: FeedParams,
): OpportunityListingFacetsState {
  const key = cacheKeyFor(baseQuery);
  const cached = listingFacetsCache.get(key) ?? null;
  const [data, setData] = useState<OpportunityListingFacetsData | null>(cached);
  const [facetsStatus, setFacetsStatus] =
    useState<OpportunityListingFacetsStatus>(cached ? "loaded" : "loading");

  useEffect(() => {
    if (listingFacetsCache.has(key)) return;

    let cancelled = false;
    void loadOpportunityListingFacetsOnce(baseQuery)
      .then((nextData) => {
        if (!cancelled) {
          setData(nextData);
          setFacetsStatus("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setData({
            facets: emptyFacets(),
            locationOptions: defaultOpportunityListingLocationOptions(baseQuery),
            sourceOptions: SOURCE_FILTER_OPTIONS.map((option) => ({
              ...option,
              count: 0,
            })),
            experienceOptions: OPPORTUNITY_EXPERIENCE_OPTIONS.map((option) => ({
              ...option,
              count: 0,
            })),
          });
          setFacetsStatus("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [baseQuery, key]);

  return { data, facetsStatus };
}

function getSort(
  value: string | null,
  defaultSort: OpportunityListingSort,
): OpportunityListingSort {
  if (value === "student" || value === "recent" || value === "deadline") {
    return value;
  }

  return defaultSort;
}

function sourceOptions(data: OpportunityListingFacetsData | null) {
  if (data?.sourceOptions.length) return data.sourceOptions;
  return SOURCE_FILTER_OPTIONS.map((option) => ({ ...option, count: 0 }));
}

function experienceOptions(data: OpportunityListingFacetsData | null) {
  if (data?.experienceOptions.length) return data.experienceOptions;
  return OPPORTUNITY_EXPERIENCE_OPTIONS.map((option) => ({ ...option, count: 0 }));
}

function companyOptions(data: OpportunityListingFacetsData | null) {
  if (data?.facets.company_counts?.length) return data.facets.company_counts;
  return (data?.facets.companies ?? []).map((company) => ({
    value: company,
    label: company,
    count: 0,
  }));
}

export function getOpportunityListingAdvancedFilterCount(
  searchParams: SearchParamReader,
): number {
  return (
    activeValues(searchParams, "company").length +
    (activeSingleValue(searchParams, "source") ? 1 : 0) +
    (activeSingleValue(searchParams, "experience") ? 1 : 0)
  );
}

function OpportunityListingAdvancedPanel({
  basePath,
  data,
  facetsStatus,
  isPending,
  idPrefix,
  onClose,
}: {
  basePath: OpportunityListingPath;
  data: OpportunityListingFacetsData | null;
  facetsStatus: OpportunityListingFacetsStatus;
  isPending: boolean;
  idPrefix: string;
  onClose?: () => void;
}) {
  const searchParams = useSearchParams();
  const { navigate } = useFeedNavigation();
  const [companySearch, setCompanySearch] = useState("");

  function commit(params: URLSearchParams) {
    params.delete("page");
    navigate(opportunityListingHref(basePath, params));
  }

  function toggleCompany(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    const values = activeValues(searchParams, "company");
    const nextValues = values.includes(value)
      ? values.filter((currentValue) => currentValue !== value)
      : [...values, value];
    setRepeatedParam(params, "company", nextValues);
    commit(params);
  }

  function setSingleParam(key: Exclude<AdvancedFilterKey, "company">, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    commit(params);
  }

  function clearAdvancedFilters() {
    const params = new URLSearchParams(searchParams.toString());
    for (const key of ["company", "source", "experience"] as const) {
      params.delete(key);
    }
    commit(params);
    onClose?.();
  }

  const companies = companyOptions(data);
  const companyNeedle = companySearch.trim().toLowerCase();
  const visibleCompanies = useMemo(() => {
    if (!companyNeedle) return companies;
    return companies.filter((option) =>
      option.label.toLowerCase().includes(companyNeedle),
    );
  }, [companies, companyNeedle]);
  const emptyLabel = countedStatusLabel(facetsStatus);
  const hasActiveFilters = getOpportunityListingAdvancedFilterCount(searchParams) > 0;

  return (
    <div aria-busy={isPending} className="space-y-5 p-4">
      {facetsStatus === "loading" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2
            className="h-4 w-4 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          Loading counts...
        </p>
      )}
      {facetsStatus === "error" && (
        <p className="text-sm text-muted-foreground" role="status">
          Counts unavailable.
        </p>
      )}

      <FilterPanelSection title="Company">
        <div className="grid gap-3">
          <Label htmlFor={`${idPrefix}-company-search`} className="sr-only">
            Search companies
          </Label>
          <Input
            id={`${idPrefix}-company-search`}
            type="search"
            placeholder="Search companies"
            value={companySearch}
            disabled={isPending || facetsStatus !== "loaded"}
            onChange={(event) => setCompanySearch(event.target.value)}
          />
          <CountedMultiSelectGroup
            label="Company"
            options={visibleCompanies}
            values={activeValues(searchParams, "company")}
            onToggle={toggleCompany}
            disabled={isPending || facetsStatus !== "loaded"}
            emptyLabel={companyNeedle ? "No company matches" : emptyLabel}
          />
        </div>
      </FilterPanelSection>

      <FilterPanelSection title="Source">
        <CountedSingleSelectGroup
          label="Source"
          options={sourceOptions(data)}
          value={activeSingleValue(searchParams, "source")}
          onSelect={(value) => setSingleParam("source", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Experience">
        <CountedSingleSelectGroup
          label="Experience"
          options={experienceOptions(data)}
          value={activeSingleValue(searchParams, "experience")}
          onSelect={(value) => setSingleParam("experience", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      {hasActiveFilters && (
        <>
          <Separator />
          <div className="flex justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isPending}
              onClick={clearAdvancedFilters}
            >
              Clear all
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export function OpportunityListingAdvancedFilters({
  basePath,
  data,
  facetsStatus,
}: {
  basePath: OpportunityListingPath;
  data: OpportunityListingFacetsData | null;
  facetsStatus: OpportunityListingFacetsStatus;
}) {
  const searchParams = useSearchParams();
  const { isFeedPending: isPending } = useFeedNavigation();
  const activeFilterCount = getOpportunityListingAdvancedFilterCount(searchParams);

  return (
    <CountedAdvancedFilterShell
      activeFilterCount={activeFilterCount}
      activeFilterLabel="opportunity filters"
      isPending={isPending}
      panelLabel="Opportunity filters"
      mobileDescription="Counted opportunity filters"
      idPrefixBase="opportunity-filter"
    >
      {({ idPrefix, onClose }) => (
        <OpportunityListingAdvancedPanel
          basePath={basePath}
          data={data}
          facetsStatus={facetsStatus}
          isPending={isPending}
          idPrefix={idPrefix}
          onClose={onClose}
        />
      )}
    </CountedAdvancedFilterShell>
  );
}

export function OpportunityListingFilterBar({
  basePath,
  baseQuery,
  defaultSort,
  data,
  facetsStatus,
}: {
  basePath: OpportunityListingPath;
  baseQuery: FeedParams;
  defaultSort: OpportunityListingSort;
  data: OpportunityListingFacetsData | null;
  facetsStatus: OpportunityListingFacetsStatus;
}) {
  const searchParams = useSearchParams();
  const query = new URLSearchParams(searchParams.toString());
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const activeLocation = getOpportunityListingLocation(query, baseQuery);
  const sort = getSort(searchParams.get("sort"), defaultSort);
  const locationOptions =
    data?.locationOptions ?? defaultOpportunityListingLocationOptions(baseQuery);

  function commit(params: URLSearchParams) {
    params.delete("page");
    navigate(opportunityListingHref(basePath, params));
  }

  function setLocation(location: OpportunityListingLocation) {
    const params = new URLSearchParams(searchParams.toString());
    applyOpportunityListingLocation(params, location, baseQuery);
    commit(params);
  }

  function setSort(nextSort: OpportunityListingSort) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextSort === defaultSort) {
      params.delete("sort");
    } else {
      params.set("sort", nextSort);
    }
    commit(params);
  }

  return (
    <div
      aria-busy={isPending}
      className={cn(
        "flex min-w-0 flex-wrap items-center justify-end gap-x-4 gap-y-2",
        isPending && "pointer-events-none cursor-progress",
      )}
    >
      {isPending && (
        <span className="sr-only" role="status">
          Updating opportunities...
        </span>
      )}

      <ListingSearchInput
        path={basePath}
        placeholder="Search opportunities..."
        ariaLabel="Search opportunities"
      />

      <OpportunityListingAdvancedFilters
        basePath={basePath}
        data={data}
        facetsStatus={facetsStatus}
      />

      <div
        className="flex min-w-0 flex-wrap items-center justify-end gap-2"
        role="group"
        aria-label="Filter opportunities by location"
      >
        <span className="eyebrow mr-1">Location</span>
        {locationOptions.map((option) => {
          const isActive = option.value === activeLocation;

          return (
            <Badge
              key={option.value}
              asChild
              variant={isActive ? "heritage" : "outline"}
              className="px-2.5 py-1"
            >
              <button
                type="button"
                aria-pressed={isActive}
                disabled={isPending}
                onClick={() => setLocation(option.value as OpportunityListingLocation)}
                className="gap-1.5 disabled:cursor-wait"
              >
                <span>{option.label}</span>
                {/* Counts arrive from a separate request, so `count` is 0 until
                    they land. Rendering that 0 told the reader "India: 0" for
                    several seconds on a page listing 22,438 jobs - a wrong number
                    is worse than no number. Show it only once loaded. */}
                {facetsStatus === "loaded" && (
                  <span className="tnum text-muted-foreground">{option.count}</span>
                )}
              </button>
            </Badge>
          );
        })}
      </div>

      <Select
        value={sort}
        disabled={isPending}
        onValueChange={(value) => setSort(value as OpportunityListingSort)}
      >
        <SelectTrigger size="sm" aria-label="Sort opportunities">
          <ArrowUpDown aria-hidden="true" />
          <SelectValue>
            {SORT_OPTIONS.find((option) => option.value === sort)?.label}
          </SelectValue>
        </SelectTrigger>
        <SelectContent align="end">
          {SORT_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function OpportunityListingActiveFilterChips({
  basePath,
  baseQuery,
  data,
}: {
  basePath: OpportunityListingPath;
  baseQuery: FeedParams;
  data: OpportunityListingFacetsData | null;
}) {
  const searchParams = useSearchParams();
  const query = new URLSearchParams(searchParams.toString());
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const locationOptions =
    data?.locationOptions ?? defaultOpportunityListingLocationOptions(baseQuery);

  function commit(params: URLSearchParams) {
    params.delete("page");
    navigate(opportunityListingHref(basePath, params));
  }

  function removeSingleParam(key: "q" | "source" | "experience") {
    const params = new URLSearchParams(searchParams.toString());
    params.delete(key);
    commit(params);
  }

  function removeCompany(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    const nextValues = activeValues(searchParams, "company").filter(
      (currentValue) => currentValue !== value,
    );
    setRepeatedParam(params, "company", nextValues);
    commit(params);
  }

  function removeLocation() {
    const params = new URLSearchParams(searchParams.toString());
    applyOpportunityListingLocation(params, "all", baseQuery);
    commit(params);
  }

  function clearAllFilters() {
    const params = new URLSearchParams(searchParams.toString());
    clearOpportunityListingFilters(params);
    commit(params);
  }

  const filters: ActiveFilterChip[] = [];
  const q = activeSingleValue(searchParams, "q");
  if (q) {
    filters.push({
      id: "q",
      label: `Search: "${q}"`,
      humanLabel: `Search: "${q}"`,
      onRemove: () => removeSingleParam("q"),
    });
  }

  const location = getOpportunityListingLocation(query, baseQuery);
  const hasLocationFilter =
    activeSingleValue(searchParams, "scope") ||
    activeSingleValue(searchParams, "country") ||
    (activeSingleValue(searchParams, "remote") &&
      activeSingleValue(searchParams, "remote") !== String(baseQuery.remote));
  if (hasLocationFilter) {
    const label =
      activeSingleValue(searchParams, "remote") === "false"
        ? "On-site"
        : optionLabel(locationOptions, location);
    filters.push({
      id: "location",
      label,
      humanLabel: `Location: ${label}`,
      onRemove: removeLocation,
    });
  }

  for (const value of activeValues(searchParams, "company")) {
    const label = optionLabel(data?.facets.company_counts, value);
    filters.push({
      id: `company:${value}`,
      label,
      humanLabel: `Company: ${label}`,
      onRemove: () => removeCompany(value),
    });
  }

  const source = activeSingleValue(searchParams, "source");
  if (source) {
    const label = optionLabel(sourceOptions(data), source);
    filters.push({
      id: "source",
      label,
      humanLabel: `Source: ${label}`,
      onRemove: () => removeSingleParam("source"),
    });
  }

  const experience = activeSingleValue(searchParams, "experience");
  if (experience) {
    const label = optionLabel(experienceOptions(data), experience);
    filters.push({
      id: "experience",
      label,
      humanLabel: `Experience: ${label}`,
      onRemove: () => removeSingleParam("experience"),
    });
  }

  const clearableFilterCount =
    (hasLocationFilter ? 1 : 0) +
    activeValues(searchParams, "company").length +
    (source ? 1 : 0) +
    (experience ? 1 : 0);

  return (
    <ActiveFilterChips
      filters={filters}
      disabled={isPending}
      onClearAll={clearAllFilters}
      showClearAll={clearableFilterCount > 0}
    />
  );
}
