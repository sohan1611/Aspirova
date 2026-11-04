"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import AuthWidget from "@/components/AuthWidget";
import DomainPicker from "@/components/DomainPicker";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { companyAlertLimitMessage, FollowLimitError, getDreamCompanies, removeDreamCompany, saveCompanyAlerts } from "@/lib/api";
import { companyAlertSavedMessage, formatDomains } from "@/lib/roleSignalQuery";
import { useSession } from "@/lib/useSession";

export default function FollowCompanyButton({ slug, companyName }: { slug: string; companyName: string }) {
  const [open, setOpen] = useState(false);
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  return <CompanyAlertButton key={`${slug}:${accessToken}`} slug={slug} companyName={companyName} accessToken={accessToken} open={open} setOpen={setOpen} />;
}

function CompanyAlertButton({ slug, companyName, accessToken, open, setOpen }: {
  slug: string; companyName: string; accessToken: string | null;
  open: boolean; setOpen: (open: boolean) => void;
}) {
  const domainsId = useId();
  const [pending, setPending] = useState(false);
  const [retry, setRetry] = useState(0);
  const [limitMessage, setLimitMessage] = useState<string | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [state, setState] = useState<{
    loaded: boolean; following: boolean; roles: string[]; error: boolean;
  }>({ loaded: false, following: false, roles: [], error: false });

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    getDreamCompanies(accessToken).then((items) => {
      const item = items.find((item) => item.company.slug === slug);
      if (!cancelled) {
        const savedRoles = item?.roles ?? [];
        setState({ loaded: true, following: Boolean(item), roles: savedRoles, error: false });
        setRoles([...savedRoles]);
      }
    }).catch(() => {
      if (!cancelled) setState({ loaded: true, following: false, roles: [], error: true });
    });
    return () => { cancelled = true; };
  }, [accessToken, retry, slug]);

  function changeOpen(next: boolean) {
    if (pending) return;
    setRoles([...state.roles]);
    if (next) setLimitMessage(null);
    setOpen(next);
  }

  async function save(remove = false) {
    if (!accessToken || pending || !state.loaded || state.error) return;
    setPending(true);
    setLimitMessage(null);
    try {
      if (remove) await removeDreamCompany(slug, accessToken);
      else await saveCompanyAlerts([slug], roles, accessToken);
      setState({ loaded: true, following: !remove, roles: remove ? [] : [...roles], error: false });
      setOpen(false);
      toast.success(remove ? "Company unfollowed" : companyAlertSavedMessage(roles, companyName));
    } catch (error) {
      if (error instanceof FollowLimitError) {
        setOpen(false);
        setLimitMessage(companyAlertLimitMessage(error));
      } else {
        toast.error("Couldn't update this company. Please try again.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mt-4 min-w-0 space-y-2">
      {accessToken && state.error ? (
        <Button type="button" variant="outline" size="sm" onClick={() => setRetry((value) => value + 1)}>
          Retry loading followed companies
        </Button>
      ) : (
        <Button type="button" variant="outline" size="sm"
          className="h-auto min-h-10 max-w-full whitespace-normal text-left [overflow-wrap:anywhere]"
          disabled={pending || Boolean(accessToken && !state.loaded)} aria-pressed={state.following}
          onClick={() => changeOpen(true)}>
          {state.following ? `Following · ${formatDomains(state.roles)}` : "Email me new roles"}
        </Button>
      )}
      {limitMessage && (
        <p role="alert" className="max-w-md text-sm text-muted-foreground">
          {limitMessage}{" "}
          <Link href="/account?section=notifications" className="underline underline-offset-4">Settings</Link>{" · "}
          <Link href="/pricing" className="underline underline-offset-4">See plans</Link>
        </p>
      )}
      <Dialog open={open} onOpenChange={changeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="break-words [overflow-wrap:anywhere]">{accessToken
              ? state.following ? `Your alert for ${companyName}` : `Get alerts from ${companyName}`
              : "Sign in to follow this company"}</DialogTitle>
            <DialogDescription>We email you the full details when this company posts a role in the domains you pick, skipping clearly senior ones.</DialogDescription>
          </DialogHeader>
          {accessToken ? (
            <div className="min-w-0 space-y-4">
              <p id={domainsId} className="text-sm font-medium">Domains</p>
              <DomainPicker aria-labelledby={domainsId} value={roles} onChange={setRoles} disabled={pending || !state.loaded || state.error} />
              <div className="flex flex-wrap gap-2">
                <Button type="button" disabled={pending || !state.loaded || state.error} onClick={() => void save()}>
                  {pending ? "Saving…" : state.following ? "Save changes" : "Create alert"}
                </Button>
                {state.following && <Button type="button" variant="outline" disabled={pending} onClick={() => void save(true)}>Stop following</Button>}
              </div>
            </div>
          ) : <AuthWidget />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
