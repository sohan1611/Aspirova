"use client";

import { AlertCircle, Bell } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getNotifications, markNotificationsRead } from "@/lib/api";
import { formatDate } from "@/lib/date";
import type { NotificationItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

interface NotificationsLoadState {
  accessToken: string | null;
  requestKey: number;
  status: "success" | "error";
  items: NotificationItem[];
}

function NotificationRow({ item }: { item: NotificationItem }) {
  const content = (
    <article
      className={cn(
        "flex gap-3 rounded-xl border border-border bg-card px-4 py-4 shadow-soft transition-colors sm:px-5",
        !item.read && "border-primary/30 bg-primary/[0.035]",
      )}
    >
      <div className="mt-1.5 flex size-2 shrink-0 items-center justify-center" aria-hidden="true">
        {!item.read && <span className="size-2 rounded-full bg-primary" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <h2 className="font-medium text-foreground">
            {!item.read && <span className="sr-only">Unread: </span>}
            {item.title}
          </h2>
          <time
            dateTime={item.created_at}
            className="shrink-0 text-xs text-muted-foreground sm:pt-0.5"
          >
            {formatDate(item.created_at)}
          </time>
        </div>
        {item.body && <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.body}</p>}
      </div>
    </article>
  );

  if (!item.opportunity_slug) {
    return content;
  }

  return (
    <Link
      href={`/opportunity/${item.opportunity_slug}`}
      className="block rounded-xl focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      {content}
    </Link>
  );
}

function NotificationsSkeleton() {
  return (
    <section className="mt-10" aria-busy="true" aria-label="Loading notifications">
      <span className="sr-only" role="status">
        Loading notifications…
      </span>
      <div className="space-y-3" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="rounded-xl border border-border bg-card px-4 py-4 shadow-soft sm:px-5">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-3 h-4 w-full max-w-2xl" />
            <Skeleton className="mt-2 h-4 w-3/4 max-w-xl" />
          </div>
        ))}
      </div>
    </section>
  );
}

export default function NotificationsPage() {
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  const [retryKey, setRetryKey] = useState(0);
  const [loadState, setLoadState] = useState<NotificationsLoadState>({
    accessToken: null,
    requestKey: -1,
    status: "success",
    items: [],
  });

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    getNotifications(accessToken)
      .then(async (response) => {
        if (cancelled) return;

        setLoadState({
          accessToken,
          requestKey: retryKey,
          status: "success",
          items: response.items,
        });

        try {
          await markNotificationsRead(accessToken);
        } catch {
          return;
        }

        if (cancelled) return;

        setLoadState((current) => {
          if (current.accessToken !== accessToken || current.requestKey !== retryKey) {
            return current;
          }

          return {
            ...current,
            items: current.items.map((item) => (item.read ? item : { ...item, read: true })),
          };
        });
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
        <p className="eyebrow">Alerts</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Notifications
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Keep up with the opportunities and career updates that matter to you.
        </p>
      </header>

      {!session ? (
        <Card className="mx-auto mt-10 max-w-xl text-center shadow-soft">
          <CardHeader>
            <Bell className="mx-auto size-9 text-primary" aria-hidden="true" />
            <CardTitle className="font-serif text-2xl">Sign in to see your notifications</CardTitle>
            <CardDescription>
              Your alerts will be waiting whenever you return to Aspirova.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <HeaderAuth triggerLabel="Sign in" />
          </CardFooter>
        </Card>
      ) : loading ? (
        <NotificationsSkeleton />
      ) : loadState.status === "error" ? (
        <Card className="mx-auto mt-10 max-w-xl text-center shadow-soft" role="alert">
          <CardHeader>
            <AlertCircle className="mx-auto size-9 text-destructive" aria-hidden="true" />
            <CardTitle className="font-serif text-2xl">We couldn&apos;t load your notifications</CardTitle>
            <CardDescription>Check your connection and try again.</CardDescription>
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
            <Bell className="size-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <h2 className="mt-5 font-serif text-xl font-semibold text-foreground">No notifications yet.</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Alerts about opportunities and your career activity will appear here.
          </p>
        </section>
      ) : (
        <section className="mt-10 space-y-3" aria-label="Notifications">
          {loadState.items.map((item) => (
            <NotificationRow key={item.id} item={item} />
          ))}
        </section>
      )}
    </main>
  );
}
