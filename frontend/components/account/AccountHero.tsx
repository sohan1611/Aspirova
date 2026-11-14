"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import AccountAvatar from "@/components/account/AccountAvatar";
import { Meter, StatusPill, StrengthRing } from "@/components/account/primitives";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/date";
import { planName } from "@/lib/planName";
import type { getProfileStrength } from "@/lib/profileCompleteness";
import type { AccountMe } from "@/lib/types";

export default function AccountHero({ account, email, displayName, avatarUrl, bookmarkStats, bookmarkStatsLoading, strength, strengthReady }: {
  account: AccountMe; email: string | null | undefined; displayName: string; avatarUrl: string | null;
  bookmarkStats: { saved: number; inProgress: number } | null; bookmarkStatsLoading: boolean;
  strength: ReturnType<typeof getProfileStrength>; strengthReady: boolean;
}) {
  const isFreePlan = account.plan.key === "free" || account.plan.status === "free";
  const planTileHref = isFreePlan ? "/pricing" : "/account?section=subscription";
  const planTileValue = isFreePlan ? "Free plan" : planName(account.plan.key);
  const planTileCaption = isFreePlan
    ? "Upgrade →"
    : account.plan.current_period_end
      ? `${account.plan.cancel_at_period_end ? "Cancels" : "Renews"} ${formatDate(account.plan.current_period_end)}`
      : "Manage plan";
  const statLinkClass = "block min-h-11 min-w-0 rounded-lg px-2 py-3 text-center outline-none transition-colors duration-200 ease-premium hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring sm:px-2";
  const stats = [
    ...(bookmarkStats ? [
      { href: "/saved", value: bookmarkStats.saved.toLocaleString(), caption: "Tracked" },
      { href: "/saved", value: bookmarkStats.inProgress.toLocaleString(), caption: "In progress" },
    ] : []),
    { href: planTileHref, value: planTileValue, caption: planTileCaption },
  ];

  return (
    <section aria-label="Your account overview" className="account-wash overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
      <div className="h-0.5 bg-gradient-to-r from-primary via-heritage to-primary/40" aria-hidden="true" />
      <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)] lg:items-center lg:gap-x-8">
        <div className="flex min-w-0 items-center gap-3 sm:gap-5">
          <StrengthRing value={strengthReady ? strength.done : 0} total={strength.total}>
            <AccountAvatar email={email} avatarUrl={avatarUrl} className="size-14 text-xl sm:size-16" />
          </StrengthRing>
          <div className="min-w-0 flex-1">
            <p className="eyebrow mb-1.5">Your account</p>
            <p className="truncate font-serif text-2xl font-bold tracking-tight text-foreground sm:text-3xl" title={displayName}>{displayName}</p>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <Badge variant={isFreePlan ? "secondary" : "heritage"}>
                {!isFreePlan && <Sparkles aria-hidden="true" />}
                {isFreePlan ? "Free" : planName(account.plan.key)}
              </Badge>
              {isFreePlan && <Link href="/pricing" className="inline-flex min-h-11 items-center rounded text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-0">Upgrade</Link>}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {email && <><span className="[overflow-wrap:anywhere]">{email}</span><span className="px-1.5" aria-hidden="true">·</span></>}
              <span className="whitespace-nowrap">Member since {formatDate(account.created_at, "long")}</span>
            </p>
          </div>
        </div>

        <dl className="order-3 flex min-w-0 divide-x divide-border border-t border-border pt-3 lg:order-none lg:border-t-0 lg:pt-0">
          {bookmarkStatsLoading ? Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="flex min-w-0 flex-1 flex-col items-center gap-2 px-2 py-3" aria-hidden="true">
              <dt className="order-2 w-full"><Skeleton className="mx-auto h-3 w-4/5" /></dt>
              <dd><Skeleton className="h-7 w-12" /></dd>
            </div>
          )) : stats.map(({ href, value, caption }) => (
            <div key={caption} className="min-w-0 flex-1">
              <dt className="sr-only">{caption}</dt>
              <dd>
                <Link href={href} className={statLinkClass}>
                  <span className="tnum block truncate font-serif text-xl font-semibold text-foreground" title={value}>{value}</span>
                  <span className="eyebrow mt-1 block leading-snug">{caption}</span>
                </Link>
              </dd>
            </div>
          ))}
        </dl>

        <div className="lg:col-span-2">
          {!strengthReady ? (
            <div className="grid gap-2.5" aria-label="Loading profile strength">
              <Skeleton className="h-1.5 w-full" /><Skeleton className="h-5 w-52 max-w-full" />
            </div>
          ) : (
            <div className="grid gap-2.5">
              <Meter value={strength.done} max={strength.total} label="Profile strength" valueText={`${strength.done} of ${strength.total} profile steps complete`} tone={strength.done === strength.total ? "success" : "primary"} />
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
                <p className="text-muted-foreground">Profile strength <strong className="tnum ml-1 font-semibold text-foreground">{strength.done} of {strength.total}</strong></p>
                {strength.nextStep ? <Link href="/account?section=profile" className="inline-flex min-h-11 items-center rounded text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-0">Next: {strength.nextStep.label} →</Link> : <StatusPill tone="success">Profile complete</StatusPill>}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
