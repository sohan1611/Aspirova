"use client";

import { Copy, Gift, Loader2, RefreshCw, UserPlus, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getReferralMe } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { useHydrated } from "@/lib/useHydrated";
import type { ReferralMe } from "@/lib/types";
import { useSession } from "@/lib/useSession";

export default function ReferralPage() {
  const session = useSession();
  const accessToken = session?.access_token;
  const [referral, setReferral] = useState<ReferralMe | null>(null);
  const [checkedAccessToken, setCheckedAccessToken] = useState<string | null>(null);
  const [hasError, setHasError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    getReferralMe(accessToken)
      .then((data) => {
        if (cancelled) return;
        setReferral(data);
        setCheckedAccessToken(accessToken);
        setHasError(false);
      })
      .catch(() => {
        if (cancelled) return;
        setReferral(null);
        setCheckedAccessToken(accessToken);
        setHasError(true);
        toast.error("We couldn't load your invite link. Please try again.");
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, retryKey]);

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-12">
      <div className="mx-auto max-w-2xl text-center">
        <Badge variant="secondary">
          <Gift aria-hidden="true" />
          Invite
        </Badge>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-foreground">
          Invite friends to Aspirova
        </h1>
        <p className="mt-2 text-muted-foreground">
          Share your link and earn 30 days of Pro Lite when a friend joins.
        </p>
      </div>

      <div className="mt-10">
        {!session ? (
          <SignedOutCard />
        ) : checkedAccessToken !== accessToken ? (
          <CheckingCard />
        ) : hasError ? (
          <ErrorCard
            onRetry={() => {
              setHasError(false);
              setCheckedAccessToken(null);
              setRetryKey((key) => key + 1);
            }}
          />
        ) : referral ? (
          <ReferralContent referral={referral} />
        ) : (
          <CheckingCard />
        )}
      </div>
    </main>
  );
}

function SignedOutCard() {
  return (
    <Card className="mx-auto max-w-xl text-center">
      <CardHeader>
        <UserPlus className="mx-auto size-8 text-primary" aria-hidden="true" />
        <CardTitle className="text-xl">Sign in to get your invite link</CardTitle>
        <CardDescription>
          Use your Aspirova account to claim referral rewards and share your personal invite.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center">
        <HeaderAuth />
      </CardFooter>
    </Card>
  );
}

function CheckingCard() {
  return (
    <Card className="mx-auto max-w-xl text-center" role="status" aria-live="polite">
      <CardContent className="flex flex-col items-center gap-3 py-6">
        <Loader2 className="size-6 animate-spin text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">Loading your invite workspace…</p>
      </CardContent>
    </Card>
  );
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <Card className="mx-auto max-w-xl text-center">
      <CardHeader>
        <CardTitle className="text-xl">We couldn&apos;t load your invite link</CardTitle>
        <CardDescription>
          Try again to refresh your referral status and copy link.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center">
        <Button type="button" onClick={onRetry}>
          <RefreshCw aria-hidden="true" />
          Retry
        </Button>
      </CardFooter>
    </Card>
  );
}

function ReferralContent({ referral }: { referral: ReferralMe }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const hydrated = useHydrated();
  const origin = hydrated && typeof window !== "undefined" ? window.location.origin : "";
  const inviteLink = origin
    ? `${origin}/?ref=${encodeURIComponent(referral.invite_code)}`
    : `/?ref=${encodeURIComponent(referral.invite_code)}`;
  const friendLabel = referral.referral_count === 1 ? "friend joined" : "friends joined";

  async function handleCopy() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(inviteLink);
        toast.success("Invite link copied");
        return;
      }
    } catch {
      // Fall through to the visible URL fallback.
    }

    const input = inputRef.current;
    if (input) {
      input.focus();
      input.select();
    }

    try {
      if (document.execCommand("copy")) {
        toast.success("Invite link copied");
        return;
      }
    } catch {
      // Selecting the text is enough when programmatic copy is unavailable.
    }

    toast("Invite link selected");
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Your invite link</CardTitle>
          <CardDescription>
            Send this to friends. Their first signed-in visit will apply your referral code.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2">
            <Label htmlFor="invite-link">Invite link</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                ref={inputRef}
                id="invite-link"
                value={inviteLink}
                readOnly
                onFocus={(event) => event.currentTarget.select()}
                className="font-mono text-sm"
              />
              <Button type="button" onClick={handleCopy} className="sm:w-fit">
                <Copy aria-hidden="true" />
                Copy
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <Users className="size-7 text-primary" aria-hidden="true" />
            <CardTitle>{referral.referral_count} {friendLabel}</CardTitle>
            <CardDescription>
              Successful signups credited to your invite link.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <Gift className="size-7 text-primary" aria-hidden="true" />
            <CardTitle>Reward status</CardTitle>
            <CardDescription>
              {referral.reward_active_until
                ? `Pro Lite active until ${formatDate(referral.reward_active_until, "long")}`
                : "Each successful referral grants 30 days of Pro Lite."}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}
