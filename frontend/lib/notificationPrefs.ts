import type { AccountMe } from "@/lib/types";

export const NOTIFICATION_KEYS = ["weekly_report", "instant_alerts", "daily_digest", "closing_soon"] as const;
export const ALWAYS_AVAILABLE_NOTIFICATION_KEYS = new Set<string>(["instant_alerts", "closing_soon"]);

export function isNotificationLocked(key: (typeof NOTIFICATION_KEYS)[number], account: AccountMe): boolean {
  return !ALWAYS_AVAILABLE_NOTIFICATION_KEYS.has(key)
    && account.plan?.features != null
    && account.plan.features[key] !== true;
}

export function isNotificationEnabled(key: (typeof NOTIFICATION_KEYS)[number], account: AccountMe): boolean {
  return !isNotificationLocked(key, account) && account.notification_prefs?.[key] !== false;
}

export function countEnabledNotifications(account: AccountMe): number {
  return NOTIFICATION_KEYS.filter((key) => isNotificationEnabled(key, account)).length;
}
