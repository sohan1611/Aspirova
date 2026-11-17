"use client";
import { loadedList, failedList, type ListState } from "@/lib/listState";
import { ListingFailure } from "@/components/ListingFeedback";

import { Bookmark } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useBookmarks } from "@/components/BookmarksProvider";
import HeaderAuth from "@/components/HeaderAuth";
import OpportunityCard from "@/components/OpportunityCard";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import BookmarkControls from "@/components/BookmarkControls";
import NextUp from "@/components/NextUp";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getBookmarks, updateBookmark } from "@/lib/api";
import { BOOKMARK_STAGES as STAGES, bookmarkCounts, stageLabel } from "@/lib/actionCenter";
import type { BookmarkStage, BookmarkUpdate, SavedOpportunityItem } from "@/lib/types";
import { useSessionState } from "@/lib/useSession";
import { cn } from "@/lib/utils";

type StageFilter = "all" | BookmarkStage;

type SavedLoadState = ListState<SavedOpportunityItem[]> & {
  accessToken: string | null;
  userId: string | null;
  requestKey: number;
  items: SavedOpportunityItem[];
};

export default function SavedPage() {
  const { syncStatus, isSaved, status, statusesReady } = useBookmarks();
  const { session, resolved } = useSessionState();
  const accessToken = session?.access_token ?? null;
  const userId = session?.user.id ?? null;
  const [retryKey, setRetryKey] = useState(0);
  const [activeStage, setActiveStage] = useState<StageFilter>("all");
  const [pendingSlugs, setPendingSlugs] = useState<Set<string>>(new Set());
  const pendingWrites = useRef(new Set<string>());
  const [loadState, setLoadState] = useState<SavedLoadState>({
    accessToken: null,
    userId: null,
    requestKey: -1,
    ...failedList<SavedOpportunityItem[]>(null),
    items: [],
  });

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    getBookmarks(accessToken)
      .then((items) => {
        if (cancelled) return;
        setLoadState({ accessToken, userId, requestKey: retryKey, ...loadedList(items, items.length), items });
      })
      .catch(() => {
        if (cancelled) return;
        setLoadState(previous => ({
          accessToken, userId, requestKey: retryKey,
          ...failedList(previous.userId === userId ? previous : null),
          items: previous.userId === userId ? previous.items : [],
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, userId, retryKey]);

  // Keep loaded card data so Undo can put a removed card back immediately.
  const savedItems = useMemo(
    () => (loadState.userId === userId ? loadState.items : [])
      .filter((item) => !statusesReady || isSaved(item.slug))
      .map((item) => ({
        ...item,
        bookmark_status: pendingSlugs.has(item.slug)
          ? item.bookmark_status
          : status(item.slug) ?? item.bookmark_status,
      })),
    [isSaved, loadState.items, loadState.userId, userId, pendingSlugs, status, statusesReady],
  );

  const counts = useMemo(() => bookmarkCounts(savedItems), [savedItems]);
  const stageCounts = counts.stages;

  const selectedStage: StageFilter =
    activeStage !== "all" && activeStage !== "saved" && stageCounts[activeStage] === 0
      ? "all"
      : activeStage;
  const visibleStages = STAGES.filter(
    (stage) => stage.value === "saved" || stageCounts[stage.value] > 0,
  );
  const filteredItems =
    selectedStage === "all"
      ? savedItems.filter(item => item.bookmark_status !== "archived")
      : savedItems.filter((item) => item.bookmark_status === selectedStage);
  const selectedStageLabel =
    selectedStage === "all" ? "All" : stageLabel(selectedStage);

  async function handleBookmarkChange(slug: string, update: BookmarkUpdate): Promise<boolean> {
    if (!accessToken || pendingWrites.current.has(slug)) return false;

    const item = savedItems.find((savedItem) => savedItem.slug === slug);
    if (!item) return false;
    if (update.status === item.bookmark_status && Object.keys(update).length === 1) return true;

    const previousStatus = item.bookmark_status;
    const nextStatus = update.status ?? previousStatus;
    pendingWrites.current.add(slug);
    setPendingSlugs((current) => new Set(current).add(slug));
    setLoadState((current) => {
      if (current.accessToken !== accessToken) return current;
      return {
        ...current,
        items: current.items.map((savedItem) =>
          savedItem.slug === slug
            ? {
              ...savedItem, bookmark_status: nextStatus,
              note: update.note === undefined ? savedItem.note : update.note,
              status_date: update.status_date === undefined ? savedItem.status_date : update.status_date,
            }
            : savedItem,
        ),
      };
    });

    if (
      nextStatus !== previousStatus && selectedStage === previousStatus &&
      previousStatus !== "saved" &&
      stageCounts[previousStatus] === 1
    ) {
      setActiveStage("all");
    }

    try {
      await updateBookmark(slug, update, accessToken);
      if (update.status) syncStatus(slug, nextStatus);
      return true;
    } catch {
      setLoadState((current) => {
        if (current.accessToken !== accessToken) return current;
        return {
          ...current,
          items: current.items.map((savedItem) =>
            savedItem.slug === slug
              ? item
              : savedItem,
          ),
        };
      });
      toast.error("Couldn't save your changes. Previous values restored.");
      return false;
    } finally {
      pendingWrites.current.delete(slug);
      setPendingSlugs((current) => {
        const next = new Set(current);
        next.delete(slug);
        return next;
      });
    }
  }

  const loading =
    !resolved ||
    (accessToken !== null &&
      (loadState.userId !== userId || (loadState.requestKey !== retryKey && loadState.loadedAt === null)));

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      {loadState.userId === userId && loadState.status === "failed" && savedItems.length > 0 && <ListingFailure retry={() => setRetryKey(current => current + 1)} loadedAt={loadState.loadedAt} pending={loadState.requestKey !== retryKey} />}
      <header className="max-w-3xl">
        <p className="eyebrow">Your action center</p>
        <h1 className="mt-3 font-serif text-4xl font-bold leading-tight tracking-tight text-foreground sm:text-5xl">
          Saved opportunities & applications
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Plan your next step and track each application from saved to a decision.
        </p>
      </header>

      {resolved && !session ? (
        <Card className="mx-auto mt-10 max-w-xl text-center shadow-soft">
          <CardHeader>
            <Bookmark className="mx-auto size-9 text-primary" aria-hidden="true" />
            <CardTitle className="font-serif text-2xl">
              Sign in to see your saved opportunities
            </CardTitle>
            <CardDescription>
              Your shortlist will stay synced whenever you return to Aspirova.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <HeaderAuth triggerLabel="Sign in" />
          </CardFooter>
        </Card>
      ) : loading ? (
        <section className="mt-10" aria-busy="true" aria-label="Loading saved opportunities">
          <span className="sr-only" role="status">
            Loading saved opportunities…
          </span>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
            {Array.from({ length: 6 }).map((_, index) => (
              <OpportunityCardSkeleton key={index} />
            ))}
          </div>
        </section>
      ) : loadState.status === "failed" && savedItems.length === 0 ? (
        <ListingFailure retry={() => setRetryKey(current => current + 1)} pending={loadState.requestKey !== retryKey} />
      ) : savedItems.length === 0 ? (
        <section role="status" aria-live="polite" className="mt-10 flex flex-col items-center rounded-lg border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
          <div className="rounded-lg border border-border bg-secondary/40 p-3">
            <Bookmark className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <h2 className="mt-5 font-serif text-xl font-bold text-foreground">
            Your shortlist is ready to grow
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Nothing saved yet — tap the bookmark on any opportunity to build your shortlist.
          </p>
          <Button asChild className="mt-5">
            <Link href="/">Browse opportunities</Link>
          </Button>
          <Button asChild variant="outline" className="mt-3 min-h-11">
            <Link href="/calendar">Explore recurring programmes</Link>
          </Button>
        </section>
      ) : (
        <>
        <NextUp items={savedItems} onPlanNext={() => {
          setActiveStage("saved");
          document.getElementById("application-tracker")?.scrollIntoView({ behavior: "smooth", block: "start" });
          document.getElementById("saved-filter")?.focus({ preventScroll: true });
        }} />
        <section id="application-tracker" className="mt-10 scroll-mt-20" aria-labelledby="tracker-heading">
          <h2 id="tracker-heading" className="mb-5 font-serif text-2xl font-bold">Application tracker</h2>
          <div
            role="group"
            aria-label="Filter saved opportunities by application stage"
            className="inline-flex max-w-full flex-wrap gap-2"
          >
            <button
              type="button"
              aria-pressed={selectedStage === "all"}
              aria-label={`All: ${counts.tracked} opportunities (excluding archived)`}
              onClick={() => setActiveStage("all")}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap min-h-11 rounded-full border px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)]",
                selectedStage === "all"
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              All
              <Badge
                variant="secondary"
                aria-hidden="true"
                className="tnum min-w-5 justify-center border-0 px-1.5 py-0.5 text-[11px] normal-case"
              >
                {counts.tracked}
              </Badge>
            </button>
            {visibleStages.map((stage) => {
              const isActive = selectedStage === stage.value;
              return (
                <button
                  key={stage.value}
                  id={stage.value === "saved" ? "saved-filter" : undefined}
                  type="button"
                  aria-pressed={isActive}
                  aria-label={`${stage.label}: ${stageCounts[stage.value]} opportunities`}
                  onClick={() => setActiveStage(stage.value)}
                  className={cn(
                    "flex items-center gap-1.5 whitespace-nowrap min-h-11 rounded-full border px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)]",
                    isActive
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  {stage.label}
                  <Badge
                    variant="secondary"
                    aria-hidden="true"
                    className="tnum min-w-5 justify-center border-0 px-1.5 py-0.5 text-[11px] normal-case"
                  >
                    {stageCounts[stage.value]}
                  </Badge>
                </button>
              );
            })}
          </div>

          <p id="saved-count" className="tnum mb-5 mt-5 text-sm text-muted-foreground">
            {filteredItems.length} of {selectedStage === "archived" ? stageCounts.archived : counts.tracked}{" "}
            {counts.tracked === 1 ? "opportunity" : "opportunities"}
            {selectedStage !== "all" && ` in ${selectedStageLabel.toLowerCase()}`}
          </p>

          {filteredItems.length === 0 ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed border-border bg-card px-5 py-8 text-left shadow-soft">
              <p className="text-sm text-muted-foreground">
                No opportunities in {selectedStageLabel.toLowerCase()} yet.
              </p>
              <Button type="button" variant="outline" size="sm" className="min-h-11" onClick={() => setActiveStage("all")}>
                View all opportunities
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {filteredItems.map((item) => (
                <article key={item.slug} aria-label={`Application tracking for ${item.title}`} className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-soft focus-within:ring-2 focus-within:ring-ring">
                  <div className="flex-1 [&>div>a]:rounded-none [&>div>a]:border-0 [&>div>a]:shadow-none">
                    <OpportunityCard item={item} />
                  </div>
                  <BookmarkControls
                    item={item}
                    pending={pendingSlugs.has(item.slug)}
                    onChange={(update) => handleBookmarkChange(item.slug, update)}
                  />
                </article>
              ))}
            </div>
          )}
        </section>
        </>
      )}
    </main>
  );
}
