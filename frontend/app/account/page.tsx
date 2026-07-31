"use client";

import { AlertCircle, Loader2, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Component,
  Suspense,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import AccountAvatar from "@/components/account/AccountAvatar";
import AccountSidebar, {
  isAccountSection,
  type AccountSectionKey,
} from "@/components/account/AccountSidebar";
import NotificationsSection from "@/components/account/NotificationsSection";
import ProfileSection from "@/components/account/ProfileSection";
import SavedSearchesSection from "@/components/account/SavedSearchesSection";
import SecuritySection from "@/components/account/SecuritySection";
import SubscriptionSection from "@/components/account/SubscriptionSection";
import HeaderAuth from "@/components/HeaderAuth";
import { Badge } from "@/components/ui/badge";
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
import { getAccount, getBookmarks } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { readStoredFieldProfile, storeFieldProfile } from "@/lib/fieldProfile";
import {
  getProfileCompleteness,
  PROFILE_COMPLETENESS_TOTAL,
} from "@/lib/profileCompleteness";
import type { FieldProfile } from "@/lib/taxonomy";
import type { AccountMe } from "@/lib/types";
import { useSession } from "@/lib/useSession";

function planName(key: string): string {
  if (key === "free") return "Free";
  if (key.startsWith("pro_lite_")) return "Pro Lite";
  if (key.startsWith("pro_")) return "Pro";
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function hasFieldProfileSelections(profile: FieldProfile | null): profile is FieldProfile {
  return Boolean(profile?.stream || profile?.divisions.length || profile?.interests.length);
}

function fieldProfilesMatch(left: FieldProfile, right: FieldProfile): boolean {
  return (
    left.stream === right.stream &&
    left.divisions.length === right.divisions.length &&
    left.divisions.every((division, index) => division === right.divisions[index]) &&
    left.interests.length === right.interests.length &&
    left.interests.every((interest, index) => interest === right.interests[index])
  );
}

export default function AccountPage() {
  return (
    <Suspense fallback={<AccountLoadingSkeleton />}>
      <AccountPageContent />
    </Suspense>
  );
}

function AccountPageContent() {
  const session = useSession();
  const accessToken = session?.access_token;
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedSection = searchParams.get("section");
  const activeSection: AccountSectionKey = isAccountSection(requestedSection)
    ? requestedSection
    : "profile";
  const [account, setAccount] = useState<AccountMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [bookmarkStats, setBookmarkStats] = useState<{
    saved: number;
    inProgress: number;
  } | null>(null);
  const [bookmarkStatsLoading, setBookmarkStatsLoading] = useState(true);
  const hydratedFieldProfileTokenRef = useRef<string | null>(null);

  const seedFieldProfileFromAccount = useCallback(
    (loadedAccount: AccountMe, localProfileAtRequest: FieldProfile) => {
      if (!accessToken || hydratedFieldProfileTokenRef.current === accessToken) return;

      const serverProfile = loadedAccount.field_profile;
      if (!hasFieldProfileSelections(serverProfile)) {
        hydratedFieldProfileTokenRef.current = accessToken;
        return;
      }

      const currentLocalProfile = readStoredFieldProfile();
      if (!fieldProfilesMatch(currentLocalProfile, localProfileAtRequest)) {
        // The local profile changed while the account request was in flight.
        hydratedFieldProfileTokenRef.current = accessToken;
        return;
      }

      if (!fieldProfilesMatch(currentLocalProfile, serverProfile)) {
        storeFieldProfile(serverProfile);
      }
      hydratedFieldProfileTokenRef.current = accessToken;
    },
    [accessToken],
  );

  const refresh = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(false);
    const localProfileAtRequest = readStoredFieldProfile();
    try {
      const loadedAccount = await getAccount(accessToken);
      seedFieldProfileFromAccount(loadedAccount, localProfileAtRequest);
      setAccount(loadedAccount);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [accessToken, seedFieldProfileFromAccount]);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    const localProfileAtRequest = readStoredFieldProfile();
    getAccount(accessToken)
      .then((loadedAccount) => {
        if (cancelled) return;
        seedFieldProfileFromAccount(loadedAccount, localProfileAtRequest);
        setAccount(loadedAccount);
        setError(false);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, seedFieldProfileFromAccount]);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    getBookmarks(accessToken)
      .then((bookmarks) => {
        if (cancelled) return;
        setBookmarkStats({
          saved: bookmarks.length,
          inProgress: bookmarks.filter(
            ({ bookmark_status }) =>
              bookmark_status === "applied" ||
              bookmark_status === "interviewing" ||
              bookmark_status === "offer",
          ).length,
        });
        setBookmarkStatsLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setBookmarkStats(null);
        setBookmarkStatsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  function selectSection(section: AccountSectionKey) {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set("section", section);
    router.replace(`/account?${nextParams.toString()}`, { scroll: false });
  }

  if (!session) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-10">
        <h1 className="font-serif text-4xl font-semibold tracking-tight text-foreground">
          Account
        </h1>
        <Card className="mx-auto mt-10 max-w-xl text-center">
          <CardHeader>
            <UserRound className="mx-auto size-9 text-primary" aria-hidden="true" />
            <CardTitle className="font-serif text-2xl">
              Sign in to manage your account
            </CardTitle>
            <CardDescription>
              Access your profile, subscription, notifications, and security settings.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <HeaderAuth triggerLabel="Sign in" />
          </CardFooter>
        </Card>
      </main>
    );
  }

  if (loading || (!account && !error)) {
    return <AccountLoadingSkeleton />;
  }

  if (error || !account) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-10">
        <h1 className="font-serif text-4xl font-semibold tracking-tight text-foreground">
          Account
        </h1>
        <Card className="mx-auto mt-10 max-w-xl text-center">
          <CardHeader>
            <AlertCircle className="mx-auto size-9 text-destructive" aria-hidden="true" />
            <CardTitle>We couldn&apos;t load your account</CardTitle>
            <CardDescription>
              Check your connection and try loading your account again.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <Button onClick={() => void refresh()}>Retry</Button>
          </CardFooter>
        </Card>
      </main>
    );
  }

  const authenticatedAccessToken = session.access_token;
  const email = account.email ?? session.user.email;
  const displayName =
    account.display_name?.trim() || email?.split("@")[0] || "Aspirova member";
  const avatarUrl: unknown = session.user.user_metadata?.avatar_url;
  const isFreePlan = account.plan.key === "free" || account.plan.status === "free";
  const { completedFields, percentage: profileCompletion } = getProfileCompleteness(account);
  const planTileHref = isFreePlan ? "/pricing" : "/account?section=subscription";
  const planTileValue = isFreePlan ? "Free plan" : planName(account.plan.key);
  const planTileCaption = isFreePlan
    ? "Upgrade →"
    : account.plan.current_period_end
      ? `${account.plan.cancel_at_period_end ? "Cancels" : "Renews"} ${formatDate(account.plan.current_period_end)}`
      : "Manage plan";

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10">
      <div className="mb-8">
        <p className="eyebrow mb-2">Your almanac</p>
        <h1 className="font-serif text-4xl font-semibold tracking-tight text-foreground">
          Account
        </h1>
        <p className="mt-2 text-muted-foreground">
          Manage your profile, plan, preferences, and security.
        </p>
      </div>

      <Card className="mb-8 shadow-soft">
        <CardContent className="flex flex-col gap-5">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-4">
              <AccountAvatar
                email={email}
                avatarUrl={typeof avatarUrl === "string" ? avatarUrl : null}
                className="size-14 text-lg"
              />
              <div className="min-w-0">
                <p className="truncate font-serif text-xl font-semibold text-foreground">
                  {displayName}
                </p>
                <p className="mt-1 truncate text-sm text-muted-foreground">{email}</p>
              </div>
            </div>
            <Badge
              className="self-start sm:self-auto"
              variant={isFreePlan ? "secondary" : "heritage"}
            >
              {planName(account.plan.key)}
            </Badge>
          </div>

          {bookmarkStatsLoading ? (
            <div
              className="grid gap-3 border-t border-border pt-5 sm:grid-cols-3"
              aria-hidden="true"
            >
              {Array.from({ length: 3 }).map((_, index) => (
                <div
                  key={index}
                  className="rounded-xl border border-border bg-secondary/25 px-4 py-3 shadow-soft"
                >
                  <Skeleton className="h-6 w-10" />
                  <Skeleton className="mt-2 h-3 w-20" />
                </div>
              ))}
            </div>
          ) : bookmarkStats ? (
            <div className="grid gap-3 border-t border-border pt-5 sm:grid-cols-3">
              <Link
                href="/saved"
                className="rounded-xl border border-border bg-secondary/25 px-4 py-3 shadow-soft transition-colors duration-200 ease-premium hover:bg-secondary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="tnum block font-serif text-xl font-semibold tracking-tight text-foreground">
                  {bookmarkStats.saved.toLocaleString()}
                </span>
                <span className="mt-1 block text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  Saved
                </span>
              </Link>
              <Link
                href="/saved"
                className="rounded-xl border border-border bg-secondary/25 px-4 py-3 shadow-soft transition-colors duration-200 ease-premium hover:bg-secondary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="tnum block font-serif text-xl font-semibold tracking-tight text-foreground">
                  {bookmarkStats.inProgress.toLocaleString()}
                </span>
                <span className="mt-1 block text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  In progress
                </span>
              </Link>
              <Link
                href={planTileHref}
                className="rounded-xl border border-border bg-secondary/25 px-4 py-3 shadow-soft transition-colors duration-200 ease-premium hover:bg-secondary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="tnum block font-serif text-xl font-semibold tracking-tight text-foreground">
                  {planTileValue}
                </span>
                <span className="mt-1 block text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  {planTileCaption}
                </span>
              </Link>
            </div>
          ) : null}

          {completedFields < PROFILE_COMPLETENESS_TOTAL && (
            <Link
              href="/account?section=profile"
              className="block rounded-lg border border-border bg-muted/30 px-4 py-3 transition-colors duration-200 ease-premium hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <p className="text-sm font-medium text-foreground">
                Profile {completedFields} of {PROFILE_COMPLETENESS_TOTAL}{" "}
                <span aria-hidden="true">·</span> Finish your profile
              </p>
              <div
                className="mt-2 h-1 overflow-hidden rounded-full bg-border/70"
                role="progressbar"
                aria-label="Profile completeness"
                aria-valuemin={0}
                aria-valuemax={PROFILE_COMPLETENESS_TOTAL}
                aria-valuenow={completedFields}
                aria-valuetext={`${completedFields} of ${PROFILE_COMPLETENESS_TOTAL} profile details complete`}
              >
                <div
                  className="h-full rounded-full bg-muted-foreground/45"
                  style={{ width: `${profileCompletion}%` }}
                />
              </div>
            </Link>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)] md:items-start">
        <AccountSidebar
          activeSection={activeSection}
          onSectionChange={selectSection}
        />
        <section aria-live="polite">
          <AccountSectionErrorBoundary key={activeSection}>
            {activeSection === "profile" && (
              <ProfileSection
                account={account}
                accessToken={authenticatedAccessToken}
                user={session.user}
                onAccountChange={setAccount}
              />
            )}
            {activeSection === "subscription" && (
              <SubscriptionSection
                account={account}
                accessToken={authenticatedAccessToken}
                refresh={refresh}
              />
            )}
            {activeSection === "notifications" && (
              <NotificationsSection
                account={account}
                accessToken={authenticatedAccessToken}
                onAccountChange={setAccount}
              />
            )}
            {activeSection === "saved" && (
              <SavedSearchesSection accessToken={authenticatedAccessToken} />
            )}
            {activeSection === "security" && <SecuritySection user={session.user} />}
          </AccountSectionErrorBoundary>
        </section>
      </div>
    </main>
  );
}

class AccountSectionErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <Card role="alert">
          <CardContent className="flex items-start gap-3 py-5">
            <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
            <div>
              <p className="font-medium text-foreground">
                Something went wrong loading this section.
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Try another settings section or refresh the page.
              </p>
            </div>
          </CardContent>
        </Card>
      );
    }

    return this.props.children;
  }
}

function AccountLoadingSkeleton() {
  return (
    <main
      className="mx-auto w-full max-w-5xl px-4 py-10"
      role="status"
      aria-label="Loading account"
    >
      <div className="flex items-center gap-3">
        <Loader2 className="size-5 animate-spin text-primary" aria-hidden="true" />
        <Skeleton className="h-10 w-44" />
      </div>
      <div className="mt-8 grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
        <Skeleton className="hidden h-64 rounded-xl md:block" />
        <div className="rounded-xl border border-border bg-card p-6">
          <Skeleton className="h-7 w-40" />
          <Skeleton className="mt-3 h-4 w-3/4" />
          <div className="mt-8 grid gap-5">
            <Skeleton className="h-16 w-16 rounded-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        </div>
      </div>
      <span className="sr-only">Loading your account settings…</span>
    </main>
  );
}
