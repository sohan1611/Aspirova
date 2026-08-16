"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useTransition,
} from "react";

interface FeedNavigationContextValue {
  navigate: (href: string) => void;
  replace: (href: string) => void;
  isFeedPending: boolean;
}

const FeedNavigationContext = createContext<FeedNavigationContextValue | null>(null);

export function FeedNavigationProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [isFeedPending, startTransition] = useTransition();

  const navigate = useCallback(
    (href: string) => {
      startTransition(() => {
        router.push(href, { scroll: false });
      });
    },
    [router],
  );

  const replace = useCallback(
    (href: string) => {
      startTransition(() => {
        router.replace(href, { scroll: false });
      });
    },
    [router],
  );

  const value = useMemo(
    () => ({ navigate, replace, isFeedPending }),
    [isFeedPending, navigate, replace],
  );

  return (
    <FeedNavigationContext.Provider value={value}>
      {children}
    </FeedNavigationContext.Provider>
  );
}

export function useFeedNavigation(): FeedNavigationContextValue {
  const context = useContext(FeedNavigationContext);
  const router = useRouter();

  const navigate = useCallback(
    (href: string) => {
      router.push(href, { scroll: false });
    },
    [router],
  );

  const replace = useCallback(
    (href: string) => {
      router.replace(href, { scroll: false });
    },
    [router],
  );

  return context ?? { navigate, replace, isFeedPending: false };
}
