"use client";

import { AlertCircle, Bookmark, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { deleteSavedSearch, getSavedSearches, setSavedSearchAlerts, updateSavedSearch } from "@/lib/api";
import { canonicalSavedSearchParams, savedSearchEditHref, savedSearchHref, savedSearchParamsFromQuery, savedSearchSummary } from "@/lib/savedSearchParams";
import { formatDate } from "@/lib/date";
import type { SavedSearchItem, SavedSearchParams } from "@/lib/types";
import { cn } from "@/lib/utils";

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

  const values = Object.fromEntries(Object.entries(params).filter(([, value]) =>
    typeof value === "string" || typeof value === "boolean" || typeof value === "number" ||
    (Array.isArray(value) && value.every((item) => typeof item === "string")),
  ));
  return savedSearchParamsFromQuery(values);
}

function isSavedSearchItem(value: unknown): value is SavedSearchItem {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    typeof (value as { id?: unknown }).id === "number"
  );
}

export default function SavedSearchesSection({ accessToken }: { accessToken: string }) {
  const headingRef = useRef<HTMLDivElement>(null);
  const renameTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SavedSearchItem | null>(null);
  const [renameTarget, setRenameTarget] = useState<SavedSearchItem | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
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

  async function handleRename(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renameTarget || renaming) return;
    setRenaming(true);
    setRenameError(null);
    try {
      const updated = await updateSavedSearch(accessToken, renameTarget.id, { name: nameDraft });
      setLoadState((current) => current.accessToken !== accessToken ? current : {
        ...current,
        items: current.items.map((item) => item.id === updated.id ? updated : item),
      });
      setRenameTarget(null);
      toast.success("Saved search renamed");
    } catch {
      setRenameError("We couldn't rename this search. Please try again.");
    } finally {
      setRenaming(false);
    }
  }

  function hasDuplicateFilters(item: SavedSearchItem) {
    const canonical = canonicalSavedSearchParams(safeSavedSearchParams(item.params));
    return loadState.items.some((other) => other.id !== item.id &&
      canonicalSavedSearchParams(safeSavedSearchParams(other.params)) === canonical);
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


  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle ref={headingRef} tabIndex={-1} className="font-serif text-2xl">Saved searches</CardTitle>
          <p className="text-xs text-muted-foreground">{loadState.items.length} of 25 saved searches</p>
          <CardDescription>
            Revisit your filters, or choose whether each search can send new-match alerts.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {loadState.items.length === 0 && (
            <div className="grid justify-items-center gap-3 py-4 text-center">
              <Bookmark className="size-6 text-muted-foreground" aria-hidden="true" />
              <p>No saved searches yet.</p>
              <p className="text-sm text-muted-foreground">Save a search from the feed to return to the same filters whenever you need them.</p>
              <Button asChild><Link href="/">Browse opportunities</Link></Button>
            </div>
          )}
          {loadState.items.map((item) => {
            const summary = savedSearchSummary(safeSavedSearchParams(item.params));
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

                {hasDuplicateFilters(item) && <p role="status" className="mt-3 text-xs text-muted-foreground">Another saved search already uses these filters.</p>}
                <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border pt-4">
                  <Button asChild variant="outline" size="sm">
                    <Link href={savedSearchEditHref(safeSavedSearchParams(item.params), item.id)}>Edit filters</Link>
                  </Button>
                  <Button type="button" variant="outline" size="sm" disabled={controlsDisabled} onClick={(event) => {
                    renameTriggerRef.current = event.currentTarget;
                    setNameDraft(item.name ?? ""); setRenameError(null); setRenameTarget(item);
                  }}>Rename</Button>
                  <Button asChild variant="outline" size="sm">
                    <Link
                      href={savedSearchHref(safeSavedSearchParams(item.params))}
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
                    onClick={() => setDeleteTarget(item)}
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
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); headingRef.current?.focus(); }}>
          <DialogHeader>
            <DialogTitle>Delete this saved search?</DialogTitle>
            <DialogDescription>
              Delete {deleteTarget?.name || savedSearchSummary(safeSavedSearchParams(deleteTarget?.params))}? Alerts for this search will stop. This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => {
              if (!deleteTarget) return;
              const id = deleteTarget.id;
              setDeleteTarget(null);
              void handleDelete(id);
            }}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={renameTarget !== null} onOpenChange={(open) => { if (!open && !renaming) setRenameTarget(null); }}>
        <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); (renameTriggerRef.current ?? headingRef.current)?.focus(); }}>
          <form onSubmit={handleRename} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Rename saved search</DialogTitle>
              <DialogDescription>Choose a name to recognise these filters.</DialogDescription>
            </DialogHeader>
            <Label htmlFor="saved-search-name">Name</Label>
            <Input id="saved-search-name" maxLength={80} value={nameDraft} disabled={renaming} onChange={(event) => setNameDraft(event.target.value)} />
            {renameTarget && hasDuplicateFilters(renameTarget) && <p role="status" className="text-xs text-muted-foreground">Another saved search already uses these filters.</p>}
            {renameError && <p role="alert" className="text-sm text-destructive">{renameError}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" disabled={renaming} onClick={() => setRenameTarget(null)}>Cancel</Button>
              <Button type="submit" disabled={renaming}>{renaming ? "Saving…" : "Save"}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
