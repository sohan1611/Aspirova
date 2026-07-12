"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";
import { addBookmark, getBookmarks, removeBookmark } from "@/lib/api";
import { useSession } from "@/lib/useSession";

interface BookmarksContextValue {
  ready: boolean;
  signedIn: boolean;
  savedCount: number;
  isSaved: (slug: string) => boolean;
  toggle: (slug: string) => Promise<void>;
}

const BookmarksContext = createContext<BookmarksContextValue | null>(null);
const EMPTY_SAVED_SLUGS = new Set<string>();

interface BookmarkState {
  accessToken: string | null;
  savedSlugs: Set<string>;
}

export function BookmarksProvider({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const accessToken = session?.access_token ?? null;
  const [bookmarkState, setBookmarkState] = useState<BookmarkState>({
    accessToken: null,
    savedSlugs: EMPTY_SAVED_SLUGS,
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
        });
      })
      .catch(() => {
        if (cancelled) return;
        setBookmarkState({ accessToken, savedSlugs: new Set() });
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
      if (!ready) return;

      const wasSaved = savedSlugs.has(slug);
      setBookmarkState((current) => {
        if (current.accessToken !== accessToken) return current;
        const next = new Set(current.savedSlugs);
        if (wasSaved) next.delete(slug);
        else next.add(slug);
        return { accessToken, savedSlugs: next };
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
          return { accessToken, savedSlugs: reverted };
        });
        toast.error("Couldn't update your saved list");
      }
    },
    [accessToken, ready, savedSlugs],
  );

  const value = useMemo<BookmarksContextValue>(
    () => ({
      ready,
      signedIn,
      savedCount: ready ? savedSlugs.size : 0,
      isSaved,
      toggle,
    }),
    [isSaved, ready, savedSlugs, signedIn, toggle],
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
