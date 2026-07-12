"use client";

import { AlertCircle, Bookmark } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import OpportunityCard from "@/components/OpportunityCard";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getBookmarks, updateBookmarkStatus } from "@/lib/api";
import type { BookmarkStage, SavedOpportunityItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

const STAGES = [
  { value: "saved", label: "Saved" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "archived", label: "Archived" },
] as const satisfies readonly { value: BookmarkStage; label: string }[];

type StageFilter = "all" | BookmarkStage;

interface SavedLoadState {
  accessToken: string | null;
  requestKey: number;
  status: "success" | "error";
  items: SavedOpportunityItem[];
}

function getStageLabel(stage: BookmarkStage): string {
  return STAGES.find((option) => option.value === stage)?.label ?? stage;
}

function StageControl({
  item,
  pending,
  onChange,
}: {
  item: SavedOpportunityItem;
  pending: boolean;
  onChange: (status: BookmarkStage) => void;
}) {
  return (
    <div className="absolute right-14 top-3 z-20">
      <Select
        value={item.bookmark_status}
        disabled={pending}
        onValueChange={(value) => onChange(value as BookmarkStage)}
      >
        <SelectTrigger
          size="sm"
          aria-busy={pending}
          aria-label={`Application stage for ${item.title}`}
          className="min-w-[7.25rem] border-border bg-background/90 px-2.5 text-xs shadow-soft backdrop-blur"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {STAGES.map((stage) => (
            <SelectItem key={stage.value} value={stage.value}>
              {stage.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export default function SavedPage() {
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  const [retryKey, setRetryKey] = useState(0);
  const [activeStage, setActiveStage] = useState<StageFilter>("all");
  const [pendingSlugs, setPendingSlugs] = useState<Set<string>>(new Set());
  const [loadState, setLoadState] = useState<SavedLoadState>({
    accessToken: null,
    requestKey: -1,
    status: "success",
    items: [],
  });

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    getBookmarks(accessToken)
      .then((items) => {
        if (cancelled) return;
        setLoadState({ accessToken, requestKey: retryKey, status: "success", items });
      })
      .catch(() => {
        if (cancelled) return;
        setLoadState({
          accessToken,
          requestKey: retryKey,
          status: "error",
          items: [],
        });
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, retryKey]);

  const stageCounts = useMemo(() => {
    const counts: Record<BookmarkStage, number> = {
      saved: 0,
      applied: 0,
      interviewing: 0,
      offer: 0,
      archived: 0,
    };

    for (const item of loadState.items) {
      counts[item.bookmark_status] += 1;
    }

    return counts;
  }, [loadState.items]);

  const selectedStage: StageFilter =
    activeStage !== "all" && activeStage !== "saved" && stageCounts[activeStage] === 0
      ? "all"
      : activeStage;
  const visibleStages = STAGES.filter(
    (stage) => stage.value === "saved" || stageCounts[stage.value] > 0,
  );
  const filteredItems =
    selectedStage === "all"
      ? loadState.items
      : loadState.items.filter((item) => item.bookmark_status === selectedStage);
  const selectedStageLabel =
    selectedStage === "all" ? "All" : getStageLabel(selectedStage);

  async function handleStageChange(slug: string, nextStatus: BookmarkStage) {
    if (!accessToken || pendingSlugs.has(slug)) return;

    const item = loadState.items.find((savedItem) => savedItem.slug === slug);
    if (!item || item.bookmark_status === nextStatus) return;

    const previousStatus = item.bookmark_status;
    setPendingSlugs((current) => new Set(current).add(slug));
    setLoadState((current) => {
      if (current.accessToken !== accessToken) return current;
      return {
        ...current,
        items: current.items.map((savedItem) =>
          savedItem.slug === slug
            ? { ...savedItem, bookmark_status: nextStatus }
            : savedItem,
        ),
      };
    });

    if (
      selectedStage === previousStatus &&
      previousStatus !== "saved" &&
      stageCounts[previousStatus] === 1
    ) {
      setActiveStage("all");
    }

    try {
      await updateBookmarkStatus(slug, nextStatus, accessToken);
    } catch {
      setLoadState((current) => {
        if (current.accessToken !== accessToken) return current;
        return {
          ...current,
          items: current.items.map((savedItem) =>
            savedItem.slug === slug
              ? { ...savedItem, bookmark_status: previousStatus }
              : savedItem,
          ),
        };
      });
      toast.error("Couldn't update this opportunity's stage");
    } finally {
      setPendingSlugs((current) => {
        const next = new Set(current);
        next.delete(slug);
        return next;
      });
    }
  }

  const loading =
    accessToken !== null &&
    (loadState.accessToken !== accessToken || loadState.requestKey !== retryKey);

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">Your shortlist</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Saved opportunities
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Track each one from saved to offer.
        </p>
      </header>

      {!session ? (
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
      ) : loadState.status === "error" ? (
        <Card className="mx-auto mt-10 max-w-xl text-center shadow-soft" role="alert">
          <CardHeader>
            <AlertCircle className="mx-auto size-9 text-destructive" aria-hidden="true" />
            <CardTitle className="font-serif text-2xl">
              We couldn&apos;t load your saved opportunities
            </CardTitle>
            <CardDescription>
              Check your connection and try loading your shortlist again.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <Button type="button" onClick={() => setRetryKey((current) => current + 1)}>
              Retry
            </Button>
          </CardFooter>
        </Card>
      ) : loadState.items.length === 0 ? (
        <section className="mt-10 flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
          <div className="rounded-lg border border-border bg-secondary/40 p-3">
            <Bookmark className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <h2 className="mt-5 font-serif text-xl font-semibold text-foreground">
            Your shortlist is ready to grow
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Nothing saved yet — tap the bookmark on any opportunity to build your shortlist.
          </p>
          <Button asChild className="mt-5">
            <Link href="/">Browse opportunities</Link>
          </Button>
        </section>
      ) : (
        <section className="mt-10" aria-labelledby="saved-count">
          <div
            role="group"
            aria-label="Filter saved opportunities by application stage"
            className="inline-flex max-w-full flex-wrap rounded-md border border-border bg-muted p-1"
          >
            <button
              type="button"
              aria-pressed={selectedStage === "all"}
              aria-label={`All: ${loadState.items.length} opportunities`}
              onClick={() => setActiveStage("all")}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)]",
                selectedStage === "all"
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              All
              <Badge
                variant="secondary"
                aria-hidden="true"
                className="tnum min-w-5 justify-center border-0 px-1.5 py-0.5 text-[11px] normal-case"
              >
                {loadState.items.length}
              </Badge>
            </button>
            {visibleStages.map((stage) => {
              const isActive = selectedStage === stage.value;
              return (
                <button
                  key={stage.value}
                  type="button"
                  aria-pressed={isActive}
                  aria-label={`${stage.label}: ${stageCounts[stage.value]} opportunities`}
                  onClick={() => setActiveStage(stage.value)}
                  className={cn(
                    "flex items-center gap-1.5 whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)]",
                    isActive
                      ? "bg-background text-foreground shadow-xs"
                      : "text-muted-foreground hover:text-foreground",
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
            {filteredItems.length} of {loadState.items.length}{" "}
            {loadState.items.length === 1 ? "opportunity" : "opportunities"}
            {selectedStage !== "all" && ` in ${selectedStageLabel.toLowerCase()}`}
          </p>

          {filteredItems.length === 0 ? (
            <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-border bg-card px-5 py-8 text-left shadow-soft">
              <p className="text-sm text-muted-foreground">
                No opportunities in {selectedStageLabel.toLowerCase()} yet.
              </p>
              <Button type="button" variant="outline" size="sm" onClick={() => setActiveStage("all")}>
                View all opportunities
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {filteredItems.map((item) => (
                <div key={item.slug} className="relative">
                  <OpportunityCard item={item} />
                  <StageControl
                    item={item}
                    pending={pendingSlugs.has(item.slug)}
                    onChange={(status) => void handleStageChange(item.slug, status)}
                  />
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
