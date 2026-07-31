"use client";

import { AlertCircle, Bookmark, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { deleteSavedSearch, getSavedSearches, setSavedSearchAlerts } from "@/lib/api";
import { getCountry } from "@/lib/countries";
import { formatDate } from "@/lib/date";
import type { SavedSearchItem, SavedSearchParams } from "@/lib/types";
import { cn } from "@/lib/utils";

const CATEGORY_LABELS: Record<string, string> = {
  internship: "Internships",
  job: "Jobs",
  hackathon: "Hackathons",
  competition: "Competitions",
};

const SOURCE_LABELS: Record<string, string> = {
  direct: "Direct from company",
  unstop: "Unstop",
  remoteok: "RemoteOK",
  devpost: "Devpost",
};

interface SavedSearchLoadState {
  accessToken: string | null;
  requestKey: number;
  status: "success" | "error";
  items: SavedSearchItem[];
}

// Saved-search responses are JSON at the client boundary. A partial/stale
// payload should render the empty state instead of crashing the account route.
function safeSavedSearchParams(params: unknown): SavedSearchParams {
  if (!params || typeof params !== "object" || Array.isArray(params)) return {};

  const values = params as Record<string, unknown>;
  return {
    q: typeof values.q === "string" ? values.q : undefined,
    category:
      values.category === "internship" ||
      values.category === "job" ||
      values.category === "hackathon" ||
      values.category === "competition"
        ? values.category
        : undefined,
    kind:
      values.kind === "roles" || values.kind === "competitions"
        ? values.kind
        : undefined,
    remote: typeof values.remote === "boolean" ? values.remote : undefined,
    scope:
      values.scope === "abroad" ||
      values.scope === "domestic" ||
      values.scope === "both"
        ? values.scope
        : undefined,
    country: typeof values.country === "string" ? values.country : undefined,
    source:
      values.source === "direct" ||
      values.source === "unstop" ||
      values.source === "remoteok" ||
      values.source === "devpost"
        ? values.source
        : undefined,
    experience: values.experience === "early" ? values.experience : undefined,
  };
}

function isSavedSearchItem(value: unknown): value is SavedSearchItem {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    typeof (value as { id?: unknown }).id === "number"
  );
}

function savedSearchSummary(params: unknown): string {
  const safeParams = safeSavedSearchParams(params);
  const parts: string[] = [];

  if (safeParams.q) parts.push(`“${safeParams.q}”`);
  if (safeParams.category) {
    parts.push(CATEGORY_LABELS[safeParams.category] ?? safeParams.category);
  } else if (safeParams.kind === "roles") {
    parts.push("Roles");
  } else if (safeParams.kind === "competitions") {
    parts.push("Competitions");
  }
  if (safeParams.remote === true) parts.push("Remote");
  if (safeParams.remote === false) parts.push("On-site");
  if (safeParams.country) {
    parts.push(
      getCountry(safeParams.country)?.name ?? safeParams.country.toUpperCase(),
    );
  } else if (safeParams.scope === "abroad") {
    parts.push("Abroad");
  } else if (safeParams.scope === "domestic") {
    parts.push("Domestic");
  } else if (safeParams.scope === "both") {
    parts.push("All locations");
  }
  if (safeParams.source) {
    parts.push(SOURCE_LABELS[safeParams.source] ?? safeParams.source);
  }
  if (safeParams.experience === "early") parts.push("Early career");

  return parts.join(" · ") || "All opportunities";
}

function savedSearchHref(params: unknown): string {
  const safeParams = safeSavedSearchParams(params);
  const search = new URLSearchParams();

  if (safeParams.q) search.set("q", safeParams.q);
  if (safeParams.category) search.set("category", safeParams.category);
  if (safeParams.kind) search.set("kind", safeParams.kind);
  if (safeParams.remote !== undefined && safeParams.remote !== null) {
    search.set("remote", String(safeParams.remote));
  }
  if (safeParams.scope) search.set("scope", safeParams.scope);
  if (safeParams.country) search.set("country", safeParams.country);
  if (safeParams.source) search.set("source", safeParams.source);
  if (safeParams.experience) search.set("experience", safeParams.experience);

  const query = search.toString();
  return query ? `/?${query}` : "/";
}

export default function SavedSearchesSection({ accessToken }: { accessToken: string }) {
  const [retryKey, setRetryKey] = useState(0);
  const [pendingAlertIds, setPendingAlertIds] = useState<Set<number>>(new Set());
  const [pendingDeleteIds, setPendingDeleteIds] = useState<Set<number>>(new Set());
  const [loadState, setLoadState] = useState<SavedSearchLoadState>({
    accessToken: null,
    requestKey: -1,
    status: "success",
    items: [],
  });

  useEffect(() => {
    let cancelled = false;

    async function loadSavedSearches() {
      try {
        const response = await getSavedSearches(accessToken);
        const items = Array.isArray(response) ? response.filter(isSavedSearchItem) : [];
        if (cancelled) return;
        setLoadState({ accessToken, requestKey: retryKey, status: "success", items });
      } catch {
        if (cancelled) return;
        setLoadState({ accessToken, requestKey: retryKey, status: "error", items: [] });
      }
    }

    void loadSavedSearches();
    return () => {
      cancelled = true;
    };
  }, [accessToken, retryKey]);

  async function handleAlertsToggle(id: number) {
    if (pendingAlertIds.has(id) || pendingDeleteIds.has(id)) return;

    const item = loadState.items.find((savedSearch) => savedSearch.id === id);
    if (!item) return;

    const previousEnabled = item.alerts_enabled;
    const nextEnabled = !previousEnabled;
    setPendingAlertIds((current) => new Set(current).add(id));
    setLoadState((current) => {
      if (current.accessToken !== accessToken) return current;
      return {
        ...current,
        items: current.items.map((savedSearch) =>
          savedSearch.id === id
            ? { ...savedSearch, alerts_enabled: nextEnabled }
            : savedSearch,
        ),
      };
    });

    try {
      const updated = await setSavedSearchAlerts(accessToken, id, nextEnabled);
      setLoadState((current) => {
        if (current.accessToken !== accessToken) return current;
        return {
          ...current,
          items: current.items.map((savedSearch) =>
            savedSearch.id === id ? updated : savedSearch,
          ),
        };
      });
      toast.success(`Alerts turned ${nextEnabled ? "on" : "off"}`);
    } catch {
      setLoadState((current) => {
        if (current.accessToken !== accessToken) return current;
        return {
          ...current,
          items: current.items.map((savedSearch) =>
            savedSearch.id === id
              ? { ...savedSearch, alerts_enabled: previousEnabled }
              : savedSearch,
          ),
        };
      });
      toast.error("We couldn't update alerts for this search.");
    } finally {
      setPendingAlertIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  async function handleDelete(id: number) {
    if (pendingDeleteIds.has(id) || pendingAlertIds.has(id)) return;

    const index = loadState.items.findIndex((savedSearch) => savedSearch.id === id);
    const item = loadState.items[index];
    if (!item) return;

    setPendingDeleteIds((current) => new Set(current).add(id));
    setLoadState((current) => {
      if (current.accessToken !== accessToken) return current;
      return {
        ...current,
        items: current.items.filter((savedSearch) => savedSearch.id !== id),
      };
    });

    try {
      await deleteSavedSearch(accessToken, id);
      toast.success("Saved search deleted");
    } catch {
      setLoadState((current) => {
        if (
          current.accessToken !== accessToken ||
          current.items.some((savedSearch) => savedSearch.id === id)
        ) {
          return current;
        }

        const items = [...current.items];
        items.splice(Math.min(index, items.length), 0, item);
        return { ...current, items };
      });
      toast.error("We couldn't delete this search. It was restored.");
    } finally {
      setPendingDeleteIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  const loading =
    loadState.accessToken !== accessToken || loadState.requestKey !== retryKey;

  if (loading) {
    return (
      <Card aria-busy="true" aria-label="Loading saved searches">
        <CardHeader>
          <CardTitle className="font-serif text-2xl">Saved searches</CardTitle>
          <CardDescription>Loading your saved filters…</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="rounded-xl border border-border bg-secondary/25 p-5 shadow-soft"
              aria-hidden="true"
            >
              <Skeleton className="h-5 w-2/5" />
              <Skeleton className="mt-3 h-4 w-4/5" />
              <Skeleton className="mt-5 h-8 w-32" />
            </div>
          ))}
        </CardContent>
        <span className="sr-only" role="status">
          Loading saved searches…
        </span>
      </Card>
    );
  }

  if (loadState.status === "error") {
    return (
      <Card className="text-center" role="alert">
        <CardHeader>
          <AlertCircle className="mx-auto size-9 text-destructive" aria-hidden="true" />
          <CardTitle className="font-serif text-2xl">
            We couldn&apos;t load your saved searches
          </CardTitle>
          <CardDescription>
            Check your connection and try loading them again.
          </CardDescription>
        </CardHeader>
        <CardFooter className="justify-center">
          <Button type="button" onClick={() => setRetryKey((current) => current + 1)}>
            Retry
          </Button>
        </CardFooter>
      </Card>
    );
  }

  if (loadState.items.length === 0) {
    return (
      <Card className="text-center">
        <CardHeader>
          <div className="mx-auto rounded-lg border border-border bg-secondary/40 p-3">
            <Bookmark className="size-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <CardTitle className="font-serif text-2xl">No saved searches yet.</CardTitle>
          <CardDescription>
            Save a search from the feed to return to the same filters whenever you need them.
          </CardDescription>
        </CardHeader>
        <CardFooter className="justify-center">
          <Button asChild>
            <Link href="/">Browse opportunities</Link>
          </Button>
        </CardFooter>
      </Card>
    );
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-2xl">Saved searches</CardTitle>
          <CardDescription>
            Revisit your filters, or choose whether each search can send new-match alerts.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {loadState.items.map((item) => {
            const summary = savedSearchSummary(item.params);
            const name = typeof item.name === "string" ? item.name.trim() : "";
            const title = name || summary;
            const createdAt = typeof item.created_at === "string" ? item.created_at : null;
            const isUpdatingAlerts = pendingAlertIds.has(item.id);
            const isDeleting = pendingDeleteIds.has(item.id);
            const controlsDisabled = isUpdatingAlerts || isDeleting;
            const titleId = `saved-search-title-${item.id}`;
            const alertsLabelId = `saved-search-alerts-${item.id}`;

            return (
              <article
                key={item.id}
                aria-busy={controlsDisabled || undefined}
                className="rounded-xl border border-border bg-secondary/20 p-5 shadow-soft"
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h2
                      id={titleId}
                      className="truncate font-serif text-lg font-semibold text-foreground"
                    >
                      {title}
                    </h2>
                    {name && (
                      <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
                    )}
                    <p className="mt-2 text-xs text-muted-foreground">
                      {createdAt ? (
                        <>
                          Saved <time dateTime={createdAt}>{formatDate(createdAt, "long")}</time>
                        </>
                      ) : (
                        "Saved recently"
                      )}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 self-start">
                    <span
                      id={alertsLabelId}
                      className="text-sm font-medium text-muted-foreground"
                    >
                      Alerts {item.alerts_enabled ? "on" : "off"}
                    </span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={item.alerts_enabled}
                      aria-labelledby={`${titleId} ${alertsLabelId}`}
                      disabled={controlsDisabled}
                      onClick={() => void handleAlertsToggle(item.id)}
                      className={cn(
                        "relative inline-flex h-6 w-11 shrink-0 rounded-full border border-transparent transition-colors duration-200 ease-premium outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60",
                        item.alerts_enabled ? "bg-primary" : "bg-muted-foreground/35",
                      )}
                    >
                      <span
                        className={cn(
                          "pointer-events-none mt-0.5 block size-5 rounded-full bg-white shadow-sm transition-transform duration-200 ease-premium",
                          item.alerts_enabled ? "translate-x-5" : "translate-x-0.5",
                        )}
                      />
                    </button>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border pt-4">
                  <Button asChild variant="outline" size="sm">
                    <Link
                      href={savedSearchHref(item.params)}
                      aria-label={`View ${title} on the opportunity feed`}
                    >
                      View
                    </Link>
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={controlsDisabled}
                    onClick={() => void handleDelete(item.id)}
                    aria-label={`Delete saved search: ${title}`}
                  >
                    <Trash2 aria-hidden="true" />
                    Delete
                  </Button>
                </div>
              </article>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
