"use client";

import { AlertCircle, Bookmark } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import HeaderAuth from "@/components/HeaderAuth";
import OpportunityCard from "@/components/OpportunityCard";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getBookmarks } from "@/lib/api";
import type { OpportunityListItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

interface SavedLoadState {
  accessToken: string | null;
  requestKey: number;
  status: "success" | "error";
  items: OpportunityListItem[];
}

export default function SavedPage() {
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  const [retryKey, setRetryKey] = useState(0);
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
          Keep the opportunities you care about close at hand.
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
          <p id="saved-count" className="tnum mb-5 text-sm text-muted-foreground">
            {loadState.items.length} saved{" "}
            {loadState.items.length === 1 ? "opportunity" : "opportunities"}
          </p>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {loadState.items.map((item) => (
              <OpportunityCard key={item.slug} item={item} />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
