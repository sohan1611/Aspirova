"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import AuthWidget from "@/components/AuthWidget";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { addDreamCompany, FollowLimitError, getDreamCompanies, removeDreamCompany } from "@/lib/api";
import { useSession } from "@/lib/useSession";

export default function FollowCompanyButton({ slug }: { slug: string }) {
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [retry, setRetry] = useState(0);
  const [limitMessage, setLimitMessage] = useState<string | null>(null);
  const [state, setState] = useState<{
    token: string | null; slug: string; following: boolean; error: boolean;
  }>({ token: null, slug, following: false, error: false });

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    getDreamCompanies(accessToken).then((items) => {
      if (!cancelled) setState({
        token: accessToken, slug, following: items.some((item) => item.company.slug === slug), error: false,
      });
    }).catch(() => {
      if (!cancelled) setState({ token: accessToken, slug, following: false, error: true });
    });
    return () => { cancelled = true; };
  }, [accessToken, retry, slug]);

  const loaded = state.token === accessToken && state.slug === slug;
  const following = Boolean(accessToken && loaded && state.following);

  async function handleFollow() {
    if (!accessToken) { setOpen(true); return; }
    if (pending || !loaded || state.error) return;
    setPending(true);
    setLimitMessage(null);
    try {
      if (following) await removeDreamCompany(slug, accessToken);
      else await addDreamCompany(slug, accessToken);
      setState({ token: accessToken, slug, following: !following, error: false });
      setOpen(false);
    } catch (error) {
      if (error instanceof FollowLimitError) {
        setOpen(false);
        const limit = error.detail.match(/\((\d+)\)/)?.[1];
        setLimitMessage(limit === "1"
          ? "Free accounts can follow 1 company. Remove one in settings, or see plans."
          : `Your plan's company follow limit${limit ? ` of ${limit}` : ""} is reached. Remove one in settings, or see plans.`);
      } else {
        toast.error("Couldn't update this company. Please try again.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mt-4 space-y-2">
      {accessToken && loaded && state.error ? (
        <Button type="button" variant="outline" size="sm" onClick={() => setRetry((value) => value + 1)}>
          Retry loading followed companies
        </Button>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm"
            disabled={pending || Boolean(accessToken && !loaded)} aria-pressed={following}
            onClick={() => void handleFollow()}>
            {following ? "Following" : "Email me new roles"}
          </Button>
          {following && <span className="text-xs text-muted-foreground">Click Following to unfollow</span>}
        </div>
      )}
      {limitMessage && (
        <p role="alert" className="max-w-md text-sm text-muted-foreground">
          {limitMessage}{" "}
          <Link href="/account?section=notifications" className="underline underline-offset-4">Settings</Link>{" · "}
          <Link href="/pricing" className="underline underline-offset-4">See plans</Link>
        </p>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{accessToken ? "Follow this company" : "Sign in to follow this company"}</DialogTitle>
            <DialogDescription>Receive new roles from this company by email.</DialogDescription>
          </DialogHeader>
          {accessToken ? <Button disabled={pending || !loaded || state.error} onClick={() => void handleFollow()}>Email me new roles</Button> : <AuthWidget />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
