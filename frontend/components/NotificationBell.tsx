"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  getNotifications,
  getUnreadCount,
  markNotificationsRead,
} from "@/lib/api";
import { formatDate } from "@/lib/date";
import type { NotificationItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

const PREVIEW_LIMIT = 8;
const UNREAD_POLL_INTERVAL_MS = 60_000;

function formatRelativeTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "";

  const elapsed = Math.max(0, Date.now() - timestamp);
  const minutes = Math.floor(elapsed / 60_000);

  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;

  return formatDate(value);
}

function NotificationPreview({
  notification,
  onNavigate,
}: {
  notification: NotificationItem;
  onNavigate: () => void;
}) {
  const content = (
    <>
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">
            {notification.title}
          </span>
          {notification.body && (
            <span className="mt-0.5 block line-clamp-2 text-xs leading-5 text-muted-foreground">
              {notification.body}
            </span>
          )}
        </span>
        {!notification.read && (
          <>
            <span className="sr-only">Unread</span>
            <span
              aria-hidden="true"
              className="mt-1.5 size-2 shrink-0 rounded-full bg-primary"
            />
          </>
        )}
      </div>
      <span className="mt-2 block text-2xs text-muted-foreground">
        {formatRelativeTime(notification.created_at)}
      </span>
    </>
  );

  const className =
    "block w-full rounded-md px-3 py-3 text-left transition-colors duration-200 ease-premium hover:bg-accent focus-visible:bg-accent focus-visible:outline-none";

  if (notification.opportunity_slug) {
    return (
      <Link
        href={`/opportunity/${notification.opportunity_slug}`}
        onClick={onNavigate}
        className={className}
      >
        {content}
      </Link>
    );
  }

  return <div className={className}>{content}</div>;
}

function SignedInNotificationBell({ accessToken }: { accessToken: string }) {
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<NotificationItem[] | null>(null);
  const [loadingNotifications, setLoadingNotifications] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [markingRead, setMarkingRead] = useState(false);
  const notificationRequestRef = useRef(0);
  const markingReadRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    const refreshUnreadCount = async () => {
      try {
        const { unread } = await getUnreadCount(accessToken);
        if (!cancelled && !markingReadRef.current) {
          setUnreadCount(unread);
        }
      } catch {
        // A transient badge refresh failure should not interrupt the header.
      }
    };

    void refreshUnreadCount();
    const interval = window.setInterval(() => {
      void refreshUnreadCount();
    }, UNREAD_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [accessToken]);

  function loadNotifications(markedReadOptimistically = false) {
    const requestId = notificationRequestRef.current + 1;
    notificationRequestRef.current = requestId;
    setLoadingNotifications(true);
    setLoadError(false);

    void getNotifications(accessToken)
      .then((response) => {
        if (notificationRequestRef.current !== requestId) return;

        setNotifications(
          markedReadOptimistically
            ? response.items.map((notification) => ({ ...notification, read: true }))
            : response.items,
        );
        setUnreadCount(markedReadOptimistically ? 0 : response.unread);
      })
      .catch(() => {
        if (notificationRequestRef.current !== requestId) return;
        setLoadError(true);
      })
      .finally(() => {
        if (notificationRequestRef.current === requestId) {
          setLoadingNotifications(false);
        }
      });
  }

  function handleMarkAllRead() {
    if (markingReadRef.current) return;

    markingReadRef.current = true;
    setMarkingRead(true);
    setUnreadCount(0);
    setNotifications((current) =>
      current?.map((notification) => ({ ...notification, read: true })) ?? current,
    );

    void markNotificationsRead(accessToken)
      .then(({ unread }) => {
        setUnreadCount(unread);
      })
      .catch(() => {
        loadNotifications();
      })
      .finally(() => {
        markingReadRef.current = false;
        setMarkingRead(false);
      });
  }

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);

    if (!nextOpen) return;

    loadNotifications(true);
    handleMarkAllRead();
  }

  const unreadLabel = `${unreadCount} unread ${
    unreadCount === 1 ? "notification" : "notifications"
  }`;
  const previewItems = notifications?.slice(0, PREVIEW_LIMIT) ?? [];

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Notifications"
          className="relative text-muted-foreground hover:bg-transparent hover:text-foreground"
        >
          <Bell aria-hidden="true" />
          {unreadCount > 0 && (
            <Badge
              aria-hidden="true"
              className="absolute -right-1 -top-1 min-w-4 rounded-full border-2 border-background bg-primary px-1 py-0 text-[10px] leading-3 text-primary-foreground"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {unreadLabel}
      </span>
      <PopoverContent
        align="end"
        className="max-h-[min(30rem,var(--radix-popover-content-available-height))] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto p-0"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <p className="font-serif text-lg font-semibold text-foreground">Notifications</p>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            disabled={markingRead || unreadCount === 0}
            onClick={handleMarkAllRead}
          >
            Mark all read
          </Button>
        </div>

        <div className="p-1">
          {loadingNotifications ? (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">Loading alerts…</p>
          ) : loadError ? (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">
              We couldn&apos;t load your notifications.
            </p>
          ) : previewItems.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">
              You&apos;re all caught up.
            </p>
          ) : (
            previewItems.map((notification) => (
              <NotificationPreview
                key={notification.id}
                notification={notification}
                onNavigate={() => setOpen(false)}
              />
            ))
          )}
        </div>

        <div className="border-t border-border p-2">
          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="block rounded-md px-3 py-2 text-center text-sm font-medium text-primary transition-colors duration-200 ease-premium hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
          >
            View all
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export default function NotificationBell() {
  const session = useSession();

  if (!session) return null;

  return <SignedInNotificationBell key={session.user.id} accessToken={session.access_token} />;
}
