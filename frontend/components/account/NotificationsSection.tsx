"use client";

import { AlarmClock, AlertCircle, Building2, CalendarRange, Eye, Lock, Mail, Newspaper, Pencil, Plus, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, EmptyState, Meter, SectionHeader, SettingsCard, StatusPill } from "@/components/account/primitives";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import CompanyFavicon from "@/components/CompanyFavicon";
import CompanyPicker from "@/components/CompanyPicker";
import DomainPicker from "@/components/DomainPicker";
import { companyAlertLimitMessage, DigestPreviewRateLimitError, FollowLimitError, getDigestPreview, getDreamCompanies, removeDreamCompany, saveCompanyAlerts, updateAccount } from "@/lib/api";
import { companyAlertSavedMessage, formatDomains } from "@/lib/roleSignalQuery";
import { withNewTabLinks } from "@/lib/emailPreview";
import type { AccountMe, CompanyListItem, DigestPreview, DigestStatus, DreamCompanyItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { isNotificationEnabled, isNotificationLocked } from "@/lib/notificationPrefs";

const NOTIFICATIONS = [
  {
    key: "weekly_report",
    label: "Weekly career report",
    description: "A weekly summary of your search progress and recommended next steps.",
  },
  {
    key: "instant_alerts",
    label: "Alerts for followed companies",
    description: "Hear as soon as a company you follow publishes a relevant opportunity.",
  },
  {
    key: "daily_digest",
    label: "Daily digest",
    description: "A concise daily roundup of new opportunities selected for you.",
  },
  {
    key: "closing_soon",
    label: "Deadline reminders",
    description: "An email when an opportunity you saved is about to close.",
  },
] as const;

const NOTIFICATION_ICONS = { weekly_report: CalendarRange, instant_alerts: Building2, daily_digest: Newspaper, closing_soon: AlarmClock };

export default function NotificationsSection({
  account,
  accessToken,
  onAccountChange,
}: {
  account: AccountMe;
  accessToken: string;
  onAccountChange: (account: AccountMe) => void;
}) {
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  // Older/stale account payloads can omit these nested JSON objects. Keep the
  // settings UI usable while the next account refresh restores the full shape.
  const notificationPrefs = account.notification_prefs ?? {};
  const planFeatures = account.plan?.features ?? {};

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
    <section aria-labelledby="account-notifications-heading" className="grid gap-6">
      <SectionHeader id="account-notifications-heading" eyebrow="Alerts" title="Notifications" description="Choose which emails you get, and which companies we watch for you." />
      <SettingsCard icon={Mail} title="Email notifications" description="Every email has a one-click unsubscribe.">
        <div className="divide-y divide-border">
          {NOTIFICATIONS.map((notification) => {
            const locked = isNotificationLocked(notification.key, account);
            const enabled = isNotificationEnabled(notification.key, account);
            const Icon = NOTIFICATION_ICONS[notification.key];

            return (
              <div key={notification.key} className="flex items-start gap-3 py-5 first:pt-0 last:pb-0 sm:gap-4">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p id={`${notification.key}-label`} className="text-sm font-medium text-foreground">{notification.label}</p>
                    {locked && (
                      <span className="inline-flex items-center gap-1.5">
                        <Lock className="size-3.5 text-muted-foreground" aria-hidden="true" />
                        <StatusPill tone="primary">Paid plans</StatusPill>
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {notification.key === "instant_alerts"
                      ? planFeatures.instant_alerts === true
                        ? "Email as soon as we find a matching role at a company you follow."
                        : "One email a day when a company you follow posts a matching role. Paid plans get it as soon as we find the role."
                      : notification.description}
                  </p>
                  {notification.key === "daily_digest" && !locked && (
                    <DigestDetails accessToken={accessToken} status={account.digest_status ?? null} enabled={enabled} />
                  )}
                  {locked && (
                    <p className="mt-1.5 text-xs font-medium text-primary">
                      Included with a paid plan ·{" "}
                      <Link href="/pricing" className="inline-flex min-h-11 items-center underline underline-offset-4 sm:min-h-0">See plans</Link>
                    </p>
                  )}
                </div>
                <Switch
                  className="mt-1"
                  checked={enabled}
                  onCheckedChange={() => { if (!locked) void handleToggle(notification.key); }}
                  disabled={locked || pendingKey !== null}
                  aria-labelledby={`${notification.key}-label`}
                  aria-busy={pendingKey === notification.key || undefined}
                />
              </div>
            );
          })}
        </div>
      </SettingsCard>
      <CompanyAlerts key={accessToken} accessToken={accessToken} alertsEnabled={notificationPrefs.instant_alerts !== false} limit={typeof planFeatures.dream_companies_limit === "number" ? planFeatures.dream_companies_limit : null} />
    </section>
  );
}


const DIGEST_TIME_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function digestStatusText(status: DigestStatus | null, enabled: boolean): string {
  const lastSent = status?.last_sent_at ? new Date(status.last_sent_at) : null;
  const delivered = lastSent && !Number.isNaN(lastSent.getTime())
    ? `Last sent ${DIGEST_TIME_FORMATTER.format(lastSent)} with ${plural(status?.last_sent_count ?? 0, "listing")}.`
    : null;
  if (status?.last_attempt_failed) {
    return `The latest digest could not be sent. ${enabled ? "It will be tried again at the next daily run. " : ""}${delivered ?? ""}`.trim();
  }
  if (delivered) return delivered;
  return enabled ? "No digest has been sent to you yet." : "You are not receiving the daily digest.";
}

function DigestDetails({
  accessToken,
  status,
  enabled,
}: {
  accessToken: string;
  status: DigestStatus | null;
  enabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<DigestPreview | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error" | "limited">("idle");

  async function showPreview() {
    setOpen(true);
    setState("loading");
    try {
      setPreview(await getDigestPreview(accessToken));
      setState("idle");
    } catch (error) {
      setState(error instanceof DigestPreviewRateLimitError ? "limited" : "error");
    }
  }

  return (
    <div className="mt-2 space-y-1.5">
      <p
        className={cn("inline-flex items-start gap-1.5 text-xs", status?.last_attempt_failed ? "text-destructive-text" : status?.last_sent_at ? "text-success dark:text-foreground" : "text-muted-foreground")}
        data-testid="digest-status"
      >
        <span aria-hidden="true" className={cn("mt-1 size-1.5 shrink-0 rounded-full", status?.last_attempt_failed ? "bg-destructive" : status?.last_sent_at ? "bg-success" : "bg-muted-foreground")} />
        {digestStatusText(status, enabled)}
      </p>
      <div>
        <Button type="button" variant="link" size="xs" className="-ml-1.5" onClick={() => void showPreview()}>
          <Eye aria-hidden="true" />Preview your next digest
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)] sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Your next digest</DialogTitle>
            <DialogDescription>
              What the email would contain if it went out now. Nothing is sent.
            </DialogDescription>
          </DialogHeader>
          {state === "loading" ? (
            <div role="status" className="space-y-4 py-6">
              <span className="sr-only">Loading digest preview…</span>
              <Skeleton className="mx-auto size-12 rounded-2xl" />
              <Skeleton className="mx-auto h-5 w-1/2" />
              <Skeleton className="h-[40dvh] w-full rounded-xl" />
            </div>
          ) : state === "limited" ? (
            <EmptyState compact icon={AlarmClock} title="Too many previews in a minute." description="Try again shortly." />
          ) : state === "error" ? (
            <EmptyState compact tone="destructive" icon={AlertCircle} title="We couldn't load the preview." description="Try again in a minute." />
          ) : preview?.html ? (
            <iframe
              title="Preview of your next daily digest"
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              srcDoc={withNewTabLinks(preview.html)}
              className="h-[60dvh] w-full rounded-md border border-border bg-white"
            />
          ) : (
            <EmptyState compact icon={Mail} title="Nothing new since your last digest yet." description="New listings appear here after the next crawl." />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CompanyAlerts({ accessToken, limit, alertsEnabled }: { accessToken: string; limit: number | null; alertsEnabled: boolean }) {
  const domainsId = useId();
  const editDomainsId = useId();
  const [items, setItems] = useState<DreamCompanyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [pickerVersion, setPickerVersion] = useState(0);
  const [chosen, setChosen] = useState<CompanyListItem[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [limitMessage, setLimitMessage] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<DreamCompanyItem["company"] | null>(null);
  const remaining = limit === null ? null : Math.max(0, limit - items.length);
  const busy = pending !== null || loading || error;

  useEffect(() => {
    let cancelled = false;
    getDreamCompanies(accessToken).then((companies) => {
      if (!cancelled) { setItems(companies); setLoading(false); setError(false); }
    }).catch(() => {
      if (!cancelled) { setLoading(false); setError(true); }
    });
    return () => { cancelled = true; };
  }, [accessToken, retry]);

  function refresh() {
    setLoading(true);
    setError(false);
    setRetry((value) => value + 1);
  }

  function showError(error: unknown) {
    if (error instanceof FollowLimitError) setLimitMessage(companyAlertLimitMessage(error));
    else toast.error("Couldn't save company alerts. Please try again.");
  }

  async function create() {
    if (busy || chosen.length === 0 || (remaining !== null && chosen.length > remaining)) return;
    setPending("create");
    setLimitMessage(null);
    try {
      await saveCompanyAlerts(chosen.map((company) => company.slug), roles, accessToken);
      toast.success(companyAlertSavedMessage(roles, chosen.length === 1 ? chosen[0].name : `${chosen.length} companies`));
      setChosen([]);
      setPickerVersion((value) => value + 1);
      setRoles([]);
      refresh();
    } catch (error) {
      showError(error);
    } finally {
      setPending(null);
    }
  }

  async function saveDomains(slug: string, name: string) {
    if (busy) return;
    setPending(`save:${slug}`);
    setLimitMessage(null);
    try {
      await saveCompanyAlerts([slug], editRoles, accessToken);
      setItems((current) => current.map((item) => item.company.slug === slug ? { ...item, roles: [...editRoles] } : item));
      setEditing(null);
      toast.success(companyAlertSavedMessage(editRoles, name));
    } catch (error) {
      showError(error);
    } finally {
      setPending(null);
    }
  }

  async function remove(slug: string) {
    if (busy) return;
    setPending(`remove:${slug}`);
    setLimitMessage(null);
    try {
      await removeDreamCompany(slug, accessToken);
      setItems((current) => current.filter((item) => item.company.slug !== slug));
      if (editing === slug) setEditing(null);
      toast.success("Company unfollowed");
    } catch {
      toast.error("Couldn't unfollow this company. Please try again.");
    } finally {
      setPending(null);
    }
  }

  return (
    <SettingsCard
      icon={Building2}
      title="Company alerts"
      description="Pick companies and domains. We email you the full details when one of them posts a matching role, skipping clearly senior ones like Senior, Staff and Director."
      action={limit !== null && !loading && !error ? (
        <div className="grid min-w-32 gap-2 text-xs text-muted-foreground">
          <p className="tnum">{items.length} of {limit} companies</p>
          <Meter value={Math.min(items.length, limit)} max={limit} label="Followed companies" valueText={`${items.length} of ${limit} companies`} tone={items.length >= limit ? "warning" : "primary"} />
          {items.length >= limit && <Link href="/pricing" className="inline-flex min-h-11 items-center font-medium text-primary underline underline-offset-4 sm:min-h-0">See plans</Link>}
        </div>
      ) : undefined}
    >
      {!alertsEnabled && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warning-foreground dark:text-warning" aria-hidden="true" />
          <p>Alerts are turned off above, so these won&apos;t email you until you turn them back on.</p>
        </div>
      )}
      {limit !== null && !loading && !error && items.length > limit && (
        <p className="mb-4 text-sm text-muted-foreground">Your plan includes alerts for {limit} {limit === 1 ? "company" : "companies"}. We use the ones you followed first.</p>
      )}
      <div className="min-w-0 rounded-xl border border-border bg-muted/30 p-4 sm:p-5">
        <p className="eyebrow mb-4">New alert</p>
        <form className="min-w-0 space-y-4" onSubmit={(event) => { event.preventDefault(); void create(); }}>
          <CompanyPicker key={pickerVersion} value={chosen} onChange={setChosen} followingSlugs={items.map((item) => item.company.slug)} maxSelectable={remaining} disabled={busy} />
          <p id={domainsId} className="text-sm font-medium">Domains</p>
          <DomainPicker aria-labelledby={domainsId} value={roles} onChange={setRoles} disabled={busy} />
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={busy || chosen.length === 0 || (remaining !== null && chosen.length > remaining)}>
              <Plus aria-hidden="true" />
              {pending === "create" ? "Creating…" : chosen.length > 1 ? `Create ${chosen.length} alerts` : "Create alert"}
            </Button>
            {chosen.length === 0 && <p className="text-xs text-muted-foreground">Pick at least one company to create an alert.</p>}
          </div>
        </form>
      </div>
      {limitMessage && <p role="alert" className="mt-3 text-sm text-muted-foreground">{limitMessage}{" "}<Link href="/pricing" className="inline-flex min-h-11 items-center underline underline-offset-4 sm:min-h-0">See plans</Link></p>}
      {loading ? (
        <div role="status" className="mt-4 divide-y divide-border">
          <span className="sr-only">Loading followed companies…</span>
          {[0, 1].map((index) => (
            <div key={index} aria-hidden="true" className="flex items-center gap-3 py-4">
              <Skeleton className="size-8 shrink-0 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/5" />
                <Skeleton className="h-3 w-3/5" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
          <p role="alert" className="flex items-center gap-2 text-sm text-destructive-text"><AlertCircle className="size-4 shrink-0" aria-hidden="true" />Couldn&apos;t load followed companies.</p>
          <Button type="button" variant="outline" size="sm" onClick={refresh}>Retry</Button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState compact icon={Building2} title="No companies yet" description="Search above to follow your first company." />
      ) : (
        <ul className="mt-4 divide-y divide-border">
          {items.map(({ company, roles: savedRoles }) => (
            <li key={company.slug} className="min-w-0 space-y-3 py-4 last:pb-0">
              <div className="flex min-w-0 flex-wrap items-center gap-3">
                <CompanyFavicon company={company} size={32} />
                <div className="min-w-0 flex-1 basis-32">
                  <Link href={`/companies/${encodeURIComponent(company.slug)}`} className="inline-flex min-h-11 items-center break-words text-sm font-medium hover:underline sm:min-h-0 [overflow-wrap:anywhere]">{company.name}</Link>
                  <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                    {savedRoles.length === 0 ? <span>{formatDomains(savedRoles)}</span> : savedRoles.map((role) => (
                      <span key={role} className="rounded-full border border-border bg-muted/50 px-2 py-0.5">{formatDomains([role])}</span>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => {
                    setEditing(company.slug); setEditRoles([...savedRoles]); setLimitMessage(null);
                  }}><Pencil aria-hidden="true" />Edit domains</Button>
                  <Button type="button" variant="destructive-ghost" size="icon-sm" aria-label={`Unfollow ${company.name}`} disabled={busy} onClick={() => setRemoveTarget(company)}>
                    <X aria-hidden="true" />
                  </Button>
                </div>
              </div>
              {editing === company.slug && (
                <div className="animate-rise space-y-3 rounded-xl border border-border bg-muted/20 p-4">
                  <p id={editDomainsId} className="text-sm font-medium">Domains</p>
                  <DomainPicker aria-labelledby={editDomainsId} value={editRoles} onChange={setEditRoles} disabled={busy} />
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" disabled={busy} onClick={() => void saveDomains(company.slug, company.name)}>{pending === `save:${company.slug}` ? "Saving…" : "Save"}</Button>
                    <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => { if (!open) setRemoveTarget(null); }}
        title={`Unfollow ${removeTarget?.name ?? ""}?`}
        description={`You'll stop getting alerts when ${removeTarget?.name ?? ""} posts a matching role. You can follow it again anytime.`}
        confirmLabel="Unfollow"
        pendingLabel="Removing…"
        pending={pending === `remove:${removeTarget?.slug}`}
        onConfirm={async () => {
          if (!removeTarget) return;
          await remove(removeTarget.slug);
          setRemoveTarget(null);
        }}
      />
    </SettingsCard>
  );
}
