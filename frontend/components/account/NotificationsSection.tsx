"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import CompanyPicker from "@/components/CompanyPicker";
import DomainPicker from "@/components/DomainPicker";
import { companyAlertLimitMessage, FollowLimitError, getDreamCompanies, removeDreamCompany, saveCompanyAlerts, updateAccount } from "@/lib/api";
import { companyAlertSavedMessage, formatDomains } from "@/lib/roleSignalQuery";
import type { AccountMe, CompanyListItem, DreamCompanyItem } from "@/lib/types";
import { cn } from "@/lib/utils";

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
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-2xl">Notifications</CardTitle>
        <CardDescription>Choose which emails you receive.</CardDescription>
      </CardHeader>
      <CardContent className="divide-y divide-border">
        {NOTIFICATIONS.map((notification) => {
          const enabled = notificationPrefs[notification.key] !== false;
          const includedWithPlan = planFeatures[notification.key] === true;

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
                  {notification.key === "instant_alerts"
                    ? includedWithPlan
                      ? "Email as soon as we find a matching role at a company you follow."
                      : "One email a day when a company you follow posts a matching role. Paid plans get it as soon as we find the role."
                    : notification.description}
                </p>
                {notification.key !== "instant_alerts" && !includedWithPlan && (
                  <p className="mt-1.5 text-xs font-medium text-primary">
                    Included with a paid plan
                  </p>
                )}
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={enabled}
                aria-labelledby={`${notification.key}-label`}
                disabled={pendingKey !== null}
                onClick={() => void handleToggle(notification.key)}
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
        <CompanyAlerts key={accessToken} accessToken={accessToken} alertsEnabled={notificationPrefs.instant_alerts !== false} limit={typeof planFeatures.dream_companies_limit === "number" ? planFeatures.dream_companies_limit : null} />
      </CardContent>
    </Card>
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
    <div className="min-w-0 py-5">
      <h3 className="font-medium text-foreground">Company alerts</h3>
      <p className="mt-1 text-sm text-muted-foreground">Pick companies and domains. We email you the full details when one of them posts a matching role.</p>
      {!alertsEnabled && <p className="mt-2 text-sm text-muted-foreground">Alerts are turned off above, so these won&apos;t email you until you turn them back on.</p>}
      {limit !== null && !loading && !error && (
        <p className="mt-3 text-sm text-muted-foreground">
          {items.length} of {limit} companies used
          {items.length >= limit && <> · <Link href="/pricing" className="underline underline-offset-4">See plans</Link></>}
        </p>
      )}
      {limit !== null && !loading && !error && items.length > limit && (
        <p className="mt-2 text-sm text-muted-foreground">Your plan includes alerts for {limit} {limit === 1 ? "company" : "companies"}. We use the ones you followed first.</p>
      )}
      <form className="mt-4 min-w-0 space-y-4" onSubmit={(event) => { event.preventDefault(); void create(); }}>
        <CompanyPicker key={pickerVersion} value={chosen} onChange={setChosen} followingSlugs={items.map((item) => item.company.slug)} maxSelectable={remaining} disabled={busy} />
        <p id={domainsId} className="text-sm font-medium">Domains</p>
        <DomainPicker aria-labelledby={domainsId} value={roles} onChange={setRoles} disabled={busy} />
        <Button type="submit" disabled={busy || chosen.length === 0 || (remaining !== null && chosen.length > remaining)}>
          {pending === "create" ? "Creating…" : chosen.length > 1 ? `Create ${chosen.length} alerts` : "Create alert"}
        </Button>
      </form>
      {limitMessage && <p role="alert" className="mt-3 text-sm text-muted-foreground">{limitMessage}{" "}<Link href="/pricing" className="underline underline-offset-4">See plans</Link></p>}
      {loading ? (
        <p role="status" className="mt-3 text-sm text-muted-foreground">Loading followed companies…</p>
      ) : error ? (
        <div className="mt-3 space-y-2">
          <p role="alert" className="text-sm text-destructive">Couldn&apos;t load followed companies.</p>
          <Button type="button" variant="outline" size="sm" onClick={refresh}>Retry</Button>
        </div>
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No company alerts yet. Search above to add your first.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {items.map(({ company, roles: savedRoles }) => (
            <li key={company.slug} className="min-w-0 space-y-3 py-3">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 flex-1 basis-40">
                  <Link href={`/companies/${encodeURIComponent(company.slug)}`} className="break-words text-sm underline underline-offset-4 [overflow-wrap:anywhere]">{company.name}</Link>
                  <p className="mt-1 text-sm text-muted-foreground">{formatDomains(savedRoles)}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => {
                    setEditing(company.slug); setEditRoles([...savedRoles]); setLimitMessage(null);
                  }}>Edit domains</Button>
                  <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void remove(company.slug)}>
                    {pending === `remove:${company.slug}` ? "Removing…" : "Remove"}
                  </Button>
                </div>
              </div>
              {editing === company.slug && (
                <div className="space-y-3 rounded-md border border-border p-3">
                  <p id={editDomainsId} className="text-sm font-medium">Domains</p>
                  <DomainPicker aria-labelledby={editDomainsId} value={editRoles} onChange={setEditRoles} disabled={busy} />
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" disabled={busy} onClick={() => void saveDomains(company.slug, company.name)}>{pending === `save:${company.slug}` ? "Saving…" : "Save"}</Button>
                    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
