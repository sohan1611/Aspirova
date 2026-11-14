"use client";

import { AlertCircle, ArrowUpRight, BookmarkPlus, Clock, Loader2, MoreHorizontal, Pencil, SlidersHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, EmptyState, Meter, SectionHeader } from "@/components/account/primitives";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { deleteSavedSearch, getSavedSearches, setSavedSearchAlerts, updateSavedSearch } from "@/lib/api";
import { canonicalSavedSearchParams, savedSearchEditHref, savedSearchHref, savedSearchParamsFromQuery, savedSearchSummary } from "@/lib/savedSearchParams";
import { formatDate } from "@/lib/date";
import type { SavedSearchItem, SavedSearchParams } from "@/lib/types";

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
  const headingRef = useRef<HTMLHeadingElement>(null);
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
      <section aria-labelledby="account-saved-searches-heading" className="grid gap-6" aria-busy="true" aria-label="Loading saved searches">
        <SectionHeader id="account-saved-searches-heading" headingRef={headingRef} eyebrow="Alerts" title="Saved searches" description="Loading your saved filters…" />
        <div className="grid gap-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="rounded-xl border border-border bg-card p-5 shadow-soft" aria-hidden="true">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <Skeleton className="h-6 w-2/5" />
                  <Skeleton className="mt-3 h-4 w-4/5" />
                  <Skeleton className="mt-3 h-3 w-1/3" />
                </div>
                <Skeleton className="h-6 w-11 rounded-full" />
              </div>
              <div className="mt-4 flex gap-2 border-t border-border pt-4">
                <Skeleton className="h-8 w-32" />
                <Skeleton className="h-8 w-24" />
              </div>
            </div>
          ))}
        </div>
        <span className="sr-only" role="status">Loading saved searches…</span>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section aria-labelledby="account-saved-searches-heading" className="grid gap-6">
        <SectionHeader id="account-saved-searches-heading" headingRef={headingRef} eyebrow="Alerts" title="Saved searches" description="Revisit your filters, or choose whether each search can send new-match alerts." />
        <div role="alert" className="rounded-xl border border-border bg-card shadow-soft">
          <EmptyState
            icon={AlertCircle}
            tone="destructive"
            title="We couldn't load your saved searches"
            description="Check your connection and try loading them again."
            action={<Button type="button" onClick={() => setRetryKey((current) => current + 1)}>Retry</Button>}
          />
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="account-saved-searches-heading" className="grid gap-6">
      <SectionHeader
        id="account-saved-searches-heading"
        headingRef={headingRef}
        eyebrow="Alerts"
        title="Saved searches"
        description="Revisit your filters, or choose whether each search can send new-match alerts."
        action={
          <div className="grid gap-2">
            <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium tnum">{loadState.items.length} of 25</span>
            <Meter value={loadState.items.length} max={25} label="Saved searches" valueText={`${loadState.items.length} of 25 saved searches`} />
          </div>
        }
      />
      <div className="grid gap-4">
        {loadState.items.length === 0 && (
          <div className="rounded-xl border border-border bg-card shadow-soft">
            <EmptyState
              icon={BookmarkPlus}
              title="No saved searches yet"
              description="Save a search from the feed to come back to the same filters, and get an email when new matches appear."
              action={<Button asChild><Link href="/">Browse opportunities</Link></Button>}
            />
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
            <article key={item.id} aria-busy={controlsDisabled || undefined} className="rounded-xl border border-border bg-card p-5 shadow-soft">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <h3 id={titleId} className="truncate font-serif text-lg font-bold text-foreground">{title}</h3>
                  {name && <p className="mt-1 text-sm text-muted-foreground">{summary}</p>}
                  <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Clock className="size-3.5 shrink-0" aria-hidden="true" />
                    {createdAt ? (
                      <>Saved <time dateTime={createdAt}>{formatDate(createdAt, "long")}</time></>
                    ) : "Saved recently"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3 self-start">
                  <p id={alertsLabelId} className="text-sm font-medium text-muted-foreground">Alerts {item.alerts_enabled ? "on" : "off"}</p>
                  <Switch
                    checked={item.alerts_enabled}
                    onCheckedChange={() => void handleAlertsToggle(item.id)}
                    disabled={controlsDisabled}
                    aria-labelledby={`${titleId} ${alertsLabelId}`}
                  />
                </div>
              </div>

              {hasDuplicateFilters(item) && <p role="status" className="mt-3 text-xs text-muted-foreground">Another saved search already uses these filters.</p>}
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
                <Button asChild variant="soft" size="sm">
                  <Link href={savedSearchHref(safeSavedSearchParams(item.params))} aria-label={`View ${title} on the opportunity feed`}>
                    <ArrowUpRight aria-hidden="true" />View results
                  </Link>
                </Button>
                <Button asChild variant="ghost" size="sm">
                  <Link href={savedSearchEditHref(safeSavedSearchParams(item.params), item.id)}><SlidersHorizontal aria-hidden="true" />Edit filters</Link>
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button id={`saved-search-actions-${item.id}`} variant="ghost" size="icon-sm" className="ml-auto" aria-label={`More actions for ${title}`} disabled={controlsDisabled}>
                      <MoreHorizontal aria-hidden="true" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" onCloseAutoFocus={(event) => { if (renameTarget || deleteTarget) event.preventDefault(); }}>
                    <DropdownMenuItem disabled={controlsDisabled} onSelect={() => {
                      renameTriggerRef.current = document.getElementById(`saved-search-actions-${item.id}`) as HTMLButtonElement | null;
                      setNameDraft(item.name ?? ""); setRenameError(null); setRenameTarget(item);
                    }}>
                      <Pencil aria-hidden="true" />Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" className="text-destructive-text data-[variant=destructive]:text-destructive-text data-[variant=destructive]:focus:text-destructive-text data-[variant=destructive]:*:[svg]:text-destructive-text!" disabled={controlsDisabled} onSelect={() => setDeleteTarget(item)}>
                      <Trash2 aria-hidden="true" />Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </article>
          );
        })}
      </div>
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete this saved search?"
        description={<>Delete {deleteTarget?.name || savedSearchSummary(safeSavedSearchParams(deleteTarget?.params))}? Alerts for this search will stop. This can&apos;t be undone.</>}
        confirmLabel="Delete"
        pendingLabel="Deleting…"
        pending={false}
        onCloseAutoFocus={(event) => { event.preventDefault(); headingRef.current?.focus(); }}
        onConfirm={() => {
          if (!deleteTarget) return;
          const id = deleteTarget.id;
          setDeleteTarget(null);
          void handleDelete(id);
        }}
      />
      <Dialog open={renameTarget !== null} onOpenChange={(open) => { if (!open && !renaming) setRenameTarget(null); }}>
        <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); (renameTriggerRef.current ?? headingRef.current)?.focus(); }}>
          <form onSubmit={handleRename} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Rename saved search</DialogTitle>
              <DialogDescription>Choose a name to recognise these filters.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <Label htmlFor="saved-search-name">Name</Label>
              <Input id="saved-search-name" aria-describedby="saved-search-name-help" maxLength={80} value={nameDraft} disabled={renaming} onChange={(event) => setNameDraft(event.target.value)} />
              <p id="saved-search-name-help" className="text-xs text-muted-foreground">Up to 80 characters.</p>
            </div>
            {renameTarget && hasDuplicateFilters(renameTarget) && <p role="status" className="text-xs text-muted-foreground">Another saved search already uses these filters.</p>}
            {renameError && <p role="alert" className="text-sm text-destructive-text">{renameError}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" disabled={renaming} onClick={() => setRenameTarget(null)}>Cancel</Button>
              <Button type="submit" disabled={renaming}>
                {renaming && <Loader2 className="animate-spin" aria-hidden="true" />}
                {renaming ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
