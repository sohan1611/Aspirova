"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { updateAccount } from "@/lib/api";
import type { AccountMe } from "@/lib/types";
import { cn } from "@/lib/utils";

const NOTIFICATIONS = [
  {
    key: "weekly_report",
    label: "Weekly career report",
    description: "A weekly summary of your search progress and recommended next steps.",
  },
  {
    key: "instant_alerts",
    label: "Instant alerts for dream companies",
    description: "Hear as soon as a tracked company publishes a relevant opportunity.",
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
                  {notification.description}
                </p>
                {!includedWithPlan && (
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
      </CardContent>
    </Card>
  );
}
