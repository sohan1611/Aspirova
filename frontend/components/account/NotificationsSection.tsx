"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getDreamCompanies, removeDreamCompany, updateAccount } from "@/lib/api";
import type { AccountMe, DreamCompanyItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const NOTIFICATIONS = [
  {
    key: "weekly_report",
    label: "Weekly career report",
    description: "A weekly summary of your search progress and recommended next steps.",
  },
  {
    key: "instant_alerts",
    label: "Instant alerts for followed companies",
    description: "Hear as soon as a company you follow publishes a relevant opportunity.",
  },
  {
    key: "daily_digest",
    label: "Daily digest",
    description: "A concise daily roundup of new opportunities selected for you.",
  },
] as const;

export default function NotificationsSection({
  account,
  accessToken,
  onAccountChange,
}: {
  account: AccountMe;
  accessToken: string;
  onAccountChange: (account: AccountMe) => void;
}) {
  const [followed, setFollowed] = useState<{
    token: string | null; items: DreamCompanyItem[]; error: boolean;
  }>({ token: null, items: [], error: false });
  const [followRetry, setFollowRetry] = useState(0);
  const [removingSlug, setRemovingSlug] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDreamCompanies(accessToken).then((items) => {
      if (!cancelled) setFollowed({ token: accessToken, items, error: false });
    }).catch(() => {
      if (!cancelled) setFollowed({ token: accessToken, items: [], error: true });
    });
    return () => { cancelled = true; };
  }, [accessToken, followRetry]);

  async function handleUnfollow(slug: string) {
    if (removingSlug) return;
    setRemovingSlug(slug);
    try {
      await removeDreamCompany(slug, accessToken);
      setFollowed((current) => current.token !== accessToken ? current : {
        ...current, items: current.items.filter((item) => item.company.slug !== slug),
      });
      toast.success("Company unfollowed");
    } catch {
      toast.error("Couldn't unfollow this company. Please try again.");
    } finally {
      setRemovingSlug(null);
    }
  }

  const [pendingKey, setPendingKey] = useState<string | null>(null);
  // Older/stale account payloads can omit these nested JSON objects. Keep the
  // settings UI usable while the next account refresh restores the full shape.
  const notificationPrefs = account.notification_prefs ?? {};
  const planFeatures = account.plan?.features ?? {};
  const entitlementKnown = account.plan?.features != null;

  async function handleToggle(key: (typeof NOTIFICATIONS)[number]["key"]) {
    const previous = account;
    const next = notificationPrefs[key] === false;
    const optimistic: AccountMe = {
      ...account,
      notification_prefs: {
        ...notificationPrefs,
        [key]: next,
      },
    };

    setPendingKey(key);
    onAccountChange(optimistic);
    try {
      const updated = await updateAccount(accessToken, {
        notification_prefs: { [key]: next },
      });
      onAccountChange(updated);
      toast.success("Notification preference updated");
    } catch {
      onAccountChange(previous);
      toast.error("We couldn't update that preference. Your setting was restored.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-2xl">Notifications</CardTitle>
        <CardDescription>Choose which emails you receive.</CardDescription>
      </CardHeader>
      <CardContent className="divide-y divide-border">
        {NOTIFICATIONS.map((notification) => {
          const locked = entitlementKnown && planFeatures[notification.key] !== true;
          const enabled = !locked && notificationPrefs[notification.key] !== false;

          return (
            <div
              key={notification.key}
              className="flex items-start justify-between gap-5 py-5 first:pt-0 last:pb-0"
            >
              <div className="min-w-0">
                <p
                  id={`${notification.key}-label`}
                  className="font-medium text-foreground"
                >
                  {notification.label}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {notification.description}
                </p>
                {locked && (
                  <p className="mt-1.5 text-xs font-medium text-primary">
                    Included with a paid plan{" "}
                    <Link href="/pricing" className="underline underline-offset-4">
                      See plans
                    </Link>
                  </p>
                )}
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={enabled}
                aria-labelledby={`${notification.key}-label`}
                disabled={locked || pendingKey !== null}
                onClick={() => {
                  if (!locked) void handleToggle(notification.key);
                }}
                className={cn(
                  "relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-transparent transition-colors duration-200 ease-premium outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60",
                  enabled ? "bg-primary" : "bg-muted-foreground/35",
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none block size-5 rounded-full bg-white shadow-sm transition-transform duration-200 ease-premium",
                    enabled ? "translate-x-5" : "translate-x-0.5",
                  )}
                />
              </button>
            </div>
          );
        })}
        <div className="py-5">
          <p className="font-medium text-foreground">Followed companies</p>
          <p className="mt-1 text-sm text-muted-foreground">New roles from companies you follow can appear in your emails.</p>
          {followed.token !== accessToken ? (
            <p className="mt-3 text-sm text-muted-foreground">Loading followed companies…</p>
          ) : followed.error ? (
            <div className="mt-3 space-y-2">
              <p role="alert" className="text-sm text-destructive">Couldn&apos;t load followed companies.</p>
              <Button variant="outline" size="sm" onClick={() => setFollowRetry((value) => value + 1)}>Retry</Button>
            </div>
          ) : followed.items.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">You aren&apos;t following any companies yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {followed.items.map(({ company }) => (
                <li key={company.slug} className="flex items-center justify-between gap-3 py-3">
                  <Link href={`/companies/${encodeURIComponent(company.slug)}`} className="text-sm underline underline-offset-4">{company.name}</Link>
                  <Button type="button" variant="outline" size="sm" disabled={removingSlug !== null}
                    onClick={() => void handleUnfollow(company.slug)}>
                    {removingSlug === company.slug ? "Removing…" : "Remove"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
