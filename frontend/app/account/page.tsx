"use client";

import { AlertCircle, Loader2, UserRound } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import AccountAvatar from "@/components/account/AccountAvatar";
import AccountSidebar, {
  isAccountSection,
  type AccountSectionKey,
} from "@/components/account/AccountSidebar";
import AppearanceSection from "@/components/account/AppearanceSection";
import NotificationsSection from "@/components/account/NotificationsSection";
import ProfileSection from "@/components/account/ProfileSection";
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
import { getAccount } from "@/lib/api";
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

  const refresh = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(false);
    try {
      setAccount(await getAccount(accessToken));
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
  const isFreePlan = account.plan.key === "free";

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
        <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
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
          <div className="flex shrink-0 items-center justify-between gap-5 sm:flex-col sm:items-end sm:justify-center sm:gap-2">
            <Badge variant={isFreePlan ? "secondary" : "heritage"}>
              {planName(account.plan.key)}
            </Badge>
            <p className="tnum text-sm text-muted-foreground">
              Member since{" "}
              {new Date(account.created_at).toLocaleDateString(undefined, {
                month: "long",
                year: "numeric",
              })}
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)] md:items-start">
        <AccountSidebar
          activeSection={activeSection}
          onSectionChange={selectSection}
        />
        <section aria-live="polite">
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
          {activeSection === "appearance" && <AppearanceSection />}
          {activeSection === "security" && <SecuritySection user={session.user} />}
        </section>
      </div>
    </main>
  );
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
