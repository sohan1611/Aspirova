"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type CompetitionSort = "recent" | "deadline";
type LocationScope = "abroad" | "domestic" | "both";
type CompetitionLocation = "all" | "online" | "india" | "abroad";
type SearchParamReader = Pick<URLSearchParams, "get">;

const COMPETITIONS_PATH = "/competitions";
const INDIA_COUNTRY_CODE = "IN";
const LOCATION_PARAM_KEYS = ["scope", "country", "remote", "remote_abroad"];

function isScope(value: string | null): value is LocationScope {
  if (value === "abroad" || value === "domestic" || value === "both") {
    return true;
  }

  return false;
}

function getSort(value: string | null): CompetitionSort {
  return value === "recent" ? "recent" : "deadline";
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

export default function CompetitionsFilterBar() {
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
    if (nextSort === "recent") {
      params.set("sort", "recent");
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
  ];

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
          Updating competitions...
        </span>
      )}

      <div
        className="flex min-w-0 flex-wrap items-center justify-end gap-2"
        role="group"
        aria-label="Filter competitions by location"
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
                onClick={() => setLocation(option.value)}
                className="disabled:cursor-wait"
              >
                {option.label}
              </button>
            </Badge>
          );
        })}
      </div>

      <div
        className="flex min-w-0 flex-wrap items-center justify-end gap-2"
        role="group"
        aria-label="Sort competitions"
      >
        <span className="eyebrow mr-1">Sort</span>
        {sortOptions.map((option) => {
          const isActive = option.value === sort;

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
                onClick={() => setSort(option.value)}
                className="disabled:cursor-wait"
              >
                {option.label}
              </button>
            </Badge>
          );
        })}
      </div>

      {isPending && (
        <Loader2
          className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
