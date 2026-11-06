"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  CompetitionsAdvancedFilters,
  type CompetitionFacetsStatus,
} from "@/components/CompetitionsAdvancedFilters";
import { useFeedNavigation } from "@/components/FeedNavigation";
import ListingSearchInput from "@/components/ListingSearchInput";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CompetitionSort } from "@/lib/competitionsQuery";
import type { Facets } from "@/lib/types";
import { cn } from "@/lib/utils";

type LocationScope = "abroad" | "domestic" | "both";
type CompetitionLocation = "all" | "online" | "india" | "abroad";
type SearchParamReader = Pick<URLSearchParams, "get">;

const COMPETITIONS_PATH = "/competitions";
const INDIA_COUNTRY_CODE = "IN";
const LOCATION_PARAM_KEYS = ["scope", "country", "remote", "remote_abroad"];

interface CompetitionsFilterBarProps {
  facets: Facets | null;
  facetsStatus: CompetitionFacetsStatus;
}

function isScope(value: string | null): value is LocationScope {
  if (value === "abroad" || value === "domestic" || value === "both") {
    return true;
  }

  return false;
}

function getSort(value: string | null): CompetitionSort {
  return value === "prize" ? "prize" : value === "recent" ? "recent" : "deadline";
}

function getLocation(searchParams: SearchParamReader): CompetitionLocation {
  const remote = searchParams.get("remote");
  const scope = searchParams.get("scope");
  const country = searchParams.get("country")?.toUpperCase();

  if (remote === "true") {
    return "online";
  }

  if (remote === "false" && country === INDIA_COUNTRY_CODE && isScope(scope)) {
    if (scope === "domestic") return "india";
    if (scope === "abroad") return "abroad";
  }

  return "all";
}

function clearLocationParams(params: URLSearchParams) {
  for (const key of LOCATION_PARAM_KEYS) {
    params.delete(key);
  }
}

function applyLocationParams(params: URLSearchParams, location: CompetitionLocation) {
  clearLocationParams(params);

  if (location === "online") {
    params.set("remote", "true");
  } else if (location === "india") {
    params.set("scope", "domestic");
    params.set("country", INDIA_COUNTRY_CODE);
    params.set("remote", "false");
  } else if (location === "abroad") {
    params.set("scope", "abroad");
    params.set("country", INDIA_COUNTRY_CODE);
    params.set("remote", "false");
  }
}

export default function CompetitionsFilterBar({
  facets,
  facetsStatus,
}: CompetitionsFilterBarProps) {
  const searchParams = useSearchParams();
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const activeLocation = getLocation(searchParams);
  const sort = getSort(searchParams.get("sort"));

  function commit(params: URLSearchParams) {
    applyLocationParams(params, getLocation(params));
    params.delete("page");
    const query = params.toString();
    navigate(query ? `${COMPETITIONS_PATH}?${query}` : COMPETITIONS_PATH);
  }

  function setLocation(location: CompetitionLocation) {
    const params = new URLSearchParams(searchParams.toString());
    applyLocationParams(params, location);
    commit(params);
  }

  function setSort(nextSort: CompetitionSort) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextSort !== "deadline") {
      params.set("sort", nextSort);
    } else {
      params.delete("sort");
    }

    commit(params);
  }

  const locationOptions: { value: CompetitionLocation; label: string }[] = [
    { value: "all", label: "All" },
    { value: "online", label: "Online" },
    { value: "india", label: "India" },
    { value: "abroad", label: "Abroad" },
  ];

  const sortOptions: { value: CompetitionSort; label: string }[] = [
    { value: "recent", label: "Newest" },
    { value: "deadline", label: "Closing soon" },
    { value: "prize", label: "Biggest prize" },
  ];

  return (
    <div
      aria-busy={isPending}
      className={cn(
        "flex w-full min-w-0 flex-wrap items-center gap-x-4 gap-y-3",
        isPending && "pointer-events-none cursor-progress",
      )}
    >
      {isPending && (
        <span className="sr-only" role="status">
          Updating competitions...
        </span>
      )}

      <ListingSearchInput
        path={COMPETITIONS_PATH}
        placeholder="Search competitions..."
        ariaLabel="Search competitions"
      />

      <CompetitionsAdvancedFilters facets={facets} facetsStatus={facetsStatus} />

      <div
        className="flex min-w-0 flex-wrap items-center gap-2"
        role="group"
        aria-label="Filter competitions by location"
      >
        <span className="sr-only">Location</span>
        {locationOptions.map((option) => {
          const isActive = option.value === activeLocation;

          return (
            <Badge
              key={option.value}
              asChild
              variant="outline"
              className={cn(
                "min-h-11 rounded-full px-3 py-1.5 sm:min-h-9",
                isActive
                  ? "border-primary bg-primary text-primary-foreground hover:bg-primary/90"
                  : "bg-card hover:bg-secondary",
              )}
            >
              <button
                type="button"
                aria-pressed={isActive}
                disabled={isPending}
                onClick={() => setLocation(option.value)}
                className="disabled:cursor-wait"
              >
                {option.label}
              </button>
            </Badge>
          );
        })}
      </div>

      {!searchParams.get("q")?.trim() && (
        <div
          className="ml-auto flex min-w-0 items-center gap-2"
          role="group"
          aria-label="Sort competitions"
        >
          <span className="text-xs text-muted-foreground">Sort by:</span>
          <Select
            value={sort}
            disabled={isPending}
            onValueChange={(value) => setSort(value as CompetitionSort)}
          >
            <SelectTrigger aria-label="Sort competitions" className="min-w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              {sortOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {isPending && (
        <Loader2
          className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
