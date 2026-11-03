"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { addBookmark, getBookmarks, removeBookmark, updateBookmarkStatus } from "@/lib/api";
import type { BookmarkStage } from "@/lib/types";
import { useSession } from "@/lib/useSession";

interface BookmarksContextValue {
  ready: boolean;
  signedIn: boolean;
  statusesReady: boolean;
  savedCount: number;
  isSaved: (slug: string) => boolean;
  toggle: (slug: string) => Promise<void>;
  status: (slug: string) => BookmarkStage | undefined;
  markApplied: (slug: string) => Promise<void>;
  syncStatus: (slug: string, status: BookmarkStage) => void;
}

const BookmarksContext = createContext<BookmarksContextValue | null>(null);
const EMPTY_SAVED_SLUGS = new Set<string>();

interface BookmarkState {
  accessToken: string | null;
  savedSlugs: Set<string>;
  statuses: Map<string, BookmarkStage>;
  statusesLoaded: boolean;
}

export function BookmarksProvider({ children }: { children: React.ReactNode }) {
  const pendingSlugs = useRef(new Set<string>());
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  const [bookmarkState, setBookmarkState] = useState<BookmarkState>({
    accessToken: null,
    savedSlugs: EMPTY_SAVED_SLUGS,
    statuses: new Map(),
    statusesLoaded: false,
  });

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    getBookmarks(accessToken)
      .then((items) => {
        if (cancelled) return;
        setBookmarkState({
          accessToken,
          savedSlugs: new Set(items.map((item) => item.slug)),
          statuses: new Map(items.map((item) => [item.slug, item.bookmark_status])),
          statusesLoaded: true,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setBookmarkState({
          accessToken, savedSlugs: new Set(), statuses: new Map(), statusesLoaded: false,
        });
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const signedIn = accessToken !== null;
  const ready = !accessToken || bookmarkState.accessToken === accessToken;
  const savedSlugs =
    accessToken && bookmarkState.accessToken === accessToken
      ? bookmarkState.savedSlugs
      : EMPTY_SAVED_SLUGS;

  const isSaved = useCallback(
    (slug: string) => ready && savedSlugs.has(slug),
    [ready, savedSlugs],
  );

  const toggle = useCallback(
    async (slug: string) => {
      if (!accessToken) {
        toast("Sign in to save opportunities");
        return;
      }
      if (!ready || pendingSlugs.current.has(slug)) return;
      pendingSlugs.current.add(slug);

      const wasSaved = savedSlugs.has(slug);
      const previousStatus = bookmarkState.statuses.get(slug);
      setBookmarkState((current) => {
        if (current.accessToken !== accessToken) return current;
        const next = new Set(current.savedSlugs);
        if (wasSaved) next.delete(slug);
        else next.add(slug);
        const statuses = new Map(current.statuses);
        if (wasSaved) statuses.delete(slug);
        else statuses.set(slug, "saved");
        return { ...current, accessToken, savedSlugs: next, statuses };
      });

      try {
        if (wasSaved) await removeBookmark(slug, accessToken);
        else await addBookmark(slug, accessToken);
      } catch {
        setBookmarkState((current) => {
          if (current.accessToken !== accessToken) return current;
          const reverted = new Set(current.savedSlugs);
          if (wasSaved) reverted.add(slug);
          else reverted.delete(slug);
          const statuses = new Map(current.statuses);
          if (previousStatus) statuses.set(slug, previousStatus);
          else statuses.delete(slug);
          return { ...current, accessToken, savedSlugs: reverted, statuses };
        });
        toast.error("Couldn't update your saved list");
      } finally {
        pendingSlugs.current.delete(slug);
      }
    },
    [accessToken, bookmarkState.statuses, ready, savedSlugs],
  );

  const status = useCallback(
    (slug: string) => ready && accessToken ? bookmarkState.statuses.get(slug) : undefined,
    [accessToken, bookmarkState.statuses, ready],
  );

  const syncStatus = useCallback((slug: string, nextStatus: BookmarkStage) => {
    setBookmarkState((current) => {
      if (!accessToken || current.accessToken !== accessToken) return current;
      return {
        ...current,
        accessToken,
        savedSlugs: new Set(current.savedSlugs).add(slug),
        statuses: new Map(current.statuses).set(slug, nextStatus),
      };
    });
  }, [accessToken]);

  const markApplied = useCallback(async (slug: string) => {
    if (!accessToken || !ready) throw new Error("Saved list is not ready");
    // Recheck on this explicit action in case the tracker changed in another tab.
    const items = await getBookmarks(accessToken);
    const existing = items.find((item) => item.slug === slug);
    const currentStatus = existing?.bookmark_status;
    if (!currentStatus || !["applied", "interviewing", "offer"].includes(currentStatus)) {
      await addBookmark(slug, accessToken);
      setBookmarkState((current) => {
        if (current.accessToken !== accessToken) return current;
        return {
          ...current,
          accessToken,
          savedSlugs: new Set(current.savedSlugs).add(slug),
          statuses: new Map(current.statuses).set(slug, currentStatus ?? "saved"),
        };
      });
      await updateBookmarkStatus(slug, "applied", accessToken);
    }
    setBookmarkState((current) => {
      if (current.accessToken !== accessToken) return current;
      return {
        ...current,
        accessToken,
        savedSlugs: new Set(current.savedSlugs).add(slug),
        statuses: new Map(current.statuses).set(slug,
          currentStatus && ["applied", "interviewing", "offer"].includes(currentStatus)
            ? currentStatus : "applied"),
      };
    });
  }, [accessToken, ready]);

  const value = useMemo<BookmarksContextValue>(
    () => ({
      ready,
      signedIn,
      statusesReady: ready && bookmarkState.statusesLoaded,
      savedCount: ready ? savedSlugs.size : 0,
      isSaved,
      toggle,
      status,
      markApplied,
      syncStatus,
    }),
    [bookmarkState.statusesLoaded, isSaved, markApplied, ready, savedSlugs, signedIn, status, syncStatus, toggle],
  );

  return (
    <BookmarksContext.Provider value={value}>
      {children}
    </BookmarksContext.Provider>
  );
}

export function useBookmarks(): BookmarksContextValue {
  const context = useContext(BookmarksContext);
  if (!context) {
    throw new Error("useBookmarks must be used within a BookmarksProvider");
  }
  return context;
}
