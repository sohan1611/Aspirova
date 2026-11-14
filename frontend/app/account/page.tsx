"use client";

import { AlertCircle, UserRound } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Component, Suspense, type ReactNode, useCallback, useEffect, useState } from "react";
import AccountHero from "@/components/account/AccountHero";
import AccountSidebar, { isAccountSection, type AccountSectionKey } from "@/components/account/AccountSidebar";
import NotificationsSection from "@/components/account/NotificationsSection";
import ProfileSection from "@/components/account/ProfileSection";
import ResumeSection from "@/components/account/ResumeSection";
import SavedSearchesSection from "@/components/account/SavedSearchesSection";
import SecuritySection from "@/components/account/SecuritySection";
import SubscriptionSection from "@/components/account/SubscriptionSection";
import { EmptyState, SettingsCard } from "@/components/account/primitives";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getAccount, getBookmarks } from "@/lib/api";
import { providersFor } from "@/lib/authProviders";
import { hasFieldProfileSelections, useFieldProfile } from "@/lib/fieldProfile";
import { countEnabledNotifications } from "@/lib/notificationPrefs";
import { planName } from "@/lib/planName";
import { getProfileStrength } from "@/lib/profileCompleteness";
import type { AccountMe } from "@/lib/types";
import { useSessionState } from "@/lib/useSession";

export default function AccountPage() {
  return (
    <Suspense fallback={<AccountLoadingSkeleton />}>
      <AccountPageContent />
    </Suspense>
  );
}

function AccountPageContent() {
  const { session, resolved } = useSessionState();
  const accessToken = session?.access_token;
  const searchParams = useSearchParams();
  const { profile: fieldProfile, hydrated: strengthReady } = useFieldProfile();
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
  const refresh = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(false);
    try {
      const loadedAccount = await getAccount(accessToken);
      setAccount(loadedAccount);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    getAccount(accessToken)
      .then((loadedAccount) => {
        if (cancelled) return;
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
  }, [accessToken]);

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

  if (!resolved) return <AccountLoadingSkeleton />;

  if (!session) {
    return (
      <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-6 sm:pt-10">
        <h1 className="sr-only">Account</h1>
        <h2 className="font-serif text-4xl font-bold tracking-tight text-foreground">Account</h2>
        <div className="mx-auto mt-10 max-w-xl rounded-xl border border-border bg-card shadow-soft">
          <EmptyState icon={UserRound} title="Sign in to manage your account" description="Access your profile, subscription, notifications, and security settings." action={<HeaderAuth triggerLabel="Sign in" />} />
        </div>
      </main>
    );
  }

  if (loading || (!account && !error)) {
    return <AccountLoadingSkeleton />;
  }

  if (error || !account) {
    return (
      <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-6 sm:pt-10">
        <h1 className="sr-only">Account</h1>
        <h2 className="font-serif text-4xl font-bold tracking-tight text-foreground">Account</h2>
        <div className="mx-auto mt-10 max-w-xl rounded-xl border border-border bg-card shadow-soft">
          <EmptyState icon={AlertCircle} title="We couldn't load your account" description="Check your connection and try loading your account again." action={<Button onClick={() => void refresh()}>Retry</Button>} />
        </div>
      </main>
    );
  }

  const authenticatedAccessToken = session.access_token;
  const email = account.email ?? session.user.email;
  const displayName = account.display_name?.trim() || email?.split("@")[0] || "Aspirova member";
  const avatarUrl: unknown = session.user.user_metadata?.avatar_url;
  const strength = getProfileStrength(account, hasFieldProfileSelections(fieldProfile));
  const providerCount = providersFor(session.user).length;
  const hints: Partial<Record<AccountSectionKey, string>> = {
    profile: strengthReady ? `${strength.done} of ${strength.total}` : "…",
    resume: account.resume ? `ATS ${account.resume.ats.score}` : "Not added",
    notifications: `${countEnabledNotifications(account)} on`,
    subscription: planName(account.plan.key) + (account.plan.cancel_at_period_end ? " · ends" : ""),
    security: `${providerCount} ${providerCount === 1 ? "method" : "methods"}`,
  };

  return (
    <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-6 sm:pt-10">
      <h1 className="sr-only">Account</h1>
      <AccountHero account={account} email={email} displayName={displayName} avatarUrl={typeof avatarUrl === "string" ? avatarUrl : null} bookmarkStats={bookmarkStats} bookmarkStatsLoading={bookmarkStatsLoading} strength={strength} strengthReady={strengthReady} />
      <div className="mt-6 grid grid-cols-1 gap-6 md:mt-8 md:grid-cols-[15rem_minmax(0,1fr)] lg:gap-10">
        <AccountSidebar activeSection={activeSection} hints={hints} />
        <section aria-live="polite" className="min-w-0">
          <AccountSectionErrorBoundary key={activeSection}>
            <div key={activeSection} className="animate-rise">

            {activeSection === "profile" && (
              <ProfileSection
                account={account}
                accessToken={authenticatedAccessToken}
                user={session.user}
                onAccountChange={setAccount}
              />
            )}
            {activeSection === "resume" && (
              <ResumeSection
                account={account}
                accessToken={authenticatedAccessToken}
                userId={session.user.id}
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
            {activeSection === "security" && <SecuritySection user={session.user} accessToken={authenticatedAccessToken} />}

            </div>
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
        <div role="alert">
          <SettingsCard icon={AlertCircle} tone="danger" title="Something went wrong loading this section." description="Try another settings section or refresh the page." />
        </div>
      );
    }

    return this.props.children;
  }
}

function AccountLoadingSkeleton() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-6 sm:pt-10" role="status" aria-label="Loading account">
      <h1 className="sr-only">Account</h1>
      <div className="overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-soft sm:p-7" aria-hidden="true">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_28rem] lg:items-center">
          <div className="flex items-center gap-4">
            <Skeleton className="size-22 shrink-0 rounded-full" />
            <div className="grid min-w-0 flex-1 gap-3"><Skeleton className="h-3 w-24" /><Skeleton className="h-8 w-3/4" /><Skeleton className="h-4 w-full" /></div>
          </div>
          <div className="flex divide-x divide-border">
            {Array.from({ length: 3 }, (_, index) => <div key={index} className="flex min-w-0 flex-1 flex-col items-center gap-2 px-2 py-3"><Skeleton className="h-7 w-12" /><Skeleton className="h-3 w-4/5" /></div>)}
          </div>
        </div>
        <Skeleton className="mt-6 h-1.5 w-full" /><Skeleton className="mt-2.5 h-5 w-52" />
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 md:mt-8 md:grid-cols-[15rem_minmax(0,1fr)] lg:gap-10" aria-hidden="true">
        <div className="hidden content-start gap-3 md:grid">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-12 w-full rounded-xl" />)}</div>
        <div className="grid gap-6">
          <div><Skeleton className="h-3 w-12" /><Skeleton className="mt-3 h-9 w-36" /><Skeleton className="mt-3 h-4 w-3/4" /></div>
          {Array.from({ length: 2 }, (_, index) => <div key={index} className="rounded-xl border border-border bg-card p-5 shadow-soft sm:p-6"><Skeleton className="h-9 w-44" /><Skeleton className="mt-5 h-11 w-full" /><Skeleton className="mt-4 h-11 w-full" /></div>)}
        </div>
      </div>
      <span className="sr-only">Loading your account settings…</span>
    </main>
  );
}
