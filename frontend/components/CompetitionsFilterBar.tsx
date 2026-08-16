"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type CompetitionSort = "recent" | "deadline";
type LocationScope = "abroad" | "domestic" | "both";

const COMPETITIONS_PATH = "/competitions";
const INDIA_COUNTRY_CODE = "IN";

function getScope(value: string | null): LocationScope {
  if (value === "abroad" || value === "domestic" || value === "both") {
    return value;
  }

  return "both";
}

function getSort(value: string | null): CompetitionSort {
  return value === "recent" ? "recent" : "deadline";
}

export default function CompetitionsFilterBar() {
  const searchParams = useSearchParams();
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const activeScope = getScope(searchParams.get("scope"));
  const sort = getSort(searchParams.get("sort"));
  const includeRemoteAbroad =
    activeScope === "domestic" && searchParams.get("remote_abroad") === "true";

  function normalizeLocationParams(params: URLSearchParams) {
    const scope = getScope(params.get("scope"));

    if (scope === "both") {
      params.delete("scope");
      params.delete("country");
      params.delete("remote_abroad");
      return;
    }

    params.set("scope", scope);
    params.set("country", INDIA_COUNTRY_CODE);
    if (scope !== "domestic" || params.get("remote_abroad") !== "true") {
      params.delete("remote_abroad");
    }
  }

  function commit(params: URLSearchParams) {
    normalizeLocationParams(params);
    params.delete("page");
    const query = params.toString();
    navigate(query ? `${COMPETITIONS_PATH}?${query}` : COMPETITIONS_PATH);
  }

  function setScope(scope: LocationScope) {
    const params = new URLSearchParams(searchParams.toString());

    if (scope === "both") {
      params.delete("scope");
      params.delete("country");
      params.delete("remote_abroad");
    } else {
      params.set("scope", scope);
      params.set("country", INDIA_COUNTRY_CODE);
      if (scope !== "domestic" || !includeRemoteAbroad) {
        params.delete("remote_abroad");
      }
    }

    commit(params);
  }

  function setRemoteAbroad(checked: boolean) {
    if (activeScope !== "domestic") return;

    const params = new URLSearchParams(searchParams.toString());
    params.set("scope", "domestic");
    params.set("country", INDIA_COUNTRY_CODE);
    if (checked) {
      params.set("remote_abroad", "true");
    } else {
      params.delete("remote_abroad");
    }

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

  const scopeOptions: { value: LocationScope; label: string }[] = [
    { value: "both", label: "Both" },
    { value: "domestic", label: "India" },
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
        {scopeOptions.map((option) => {
          const isActive = option.value === activeScope;

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
                onClick={() => setScope(option.value)}
                className="disabled:cursor-wait"
              >
                {option.label}
              </button>
            </Badge>
          );
        })}
      </div>

      {activeScope === "domestic" && (
        <div className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-muted px-2.5 py-1.5">
          <input
            id="competitions-remote-abroad"
            type="checkbox"
            checked={includeRemoteAbroad}
            disabled={isPending}
            onChange={(event) => setRemoteAbroad(event.target.checked)}
            className="h-4 w-4 shrink-0 rounded border-border bg-background accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-wait disabled:opacity-50"
          />
          <Label
            htmlFor="competitions-remote-abroad"
            className="cursor-pointer whitespace-nowrap text-sm leading-tight"
          >
            Include remote roles as well
          </Label>
        </div>
      )}

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
