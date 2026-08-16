"use client";

import { Pencil, Sparkles } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useSyncExternalStore } from "react";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Button } from "@/components/ui/button";
import { getCountry } from "@/lib/countries";
import { requestOnboarding, useFieldProfile } from "@/lib/fieldProfile";
import { useSkillNames } from "@/lib/personalizationSkills";
import { buildFeedTerms } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";

const COUNTRY_STORAGE_KEY = "aspirova.country";
const COUNTRY_EVENT = "aspirova:country-change";

function readStoredCountryCode(): string | null {
  try {
    return window.localStorage.getItem(COUNTRY_STORAGE_KEY);
  } catch {
    return null;
  }
}

function subscribeStoredCountry(onChange: () => void): () => void {
  window.addEventListener(COUNTRY_EVENT, onChange);
  window.addEventListener("storage", onChange);

  return () => {
    window.removeEventListener(COUNTRY_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function hrefFor(params: URLSearchParams): string {
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export default function ForYouControl() {
  const searchParams = useSearchParams();
  const { profile, hydrated } = useFieldProfile();
  const { skillNames, hydrated: skillsHydrated } = useSkillNames();
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const storedCountryCode = useSyncExternalStore(
    subscribeStoredCountry,
    readStoredCountryCode,
    () => null,
  );
  const countryCode = storedCountryCode && getCountry(storedCountryCode) ? storedCountryCode : null;
  const terms = buildFeedTerms(profile, skillNames);
  const isForYou =
    (searchParams.get("view") === "foryou" || Boolean(searchParams.get("skills")?.trim())) &&
    !searchParams.get("q");

  function activateForYou() {
    if (profile.interests.length === 0 && skillNames.length === 0) {
      requestOnboarding();
      return;
    }

    const params = new URLSearchParams(searchParams.toString());
    params.delete("q");
    params.set("view", "foryou");
    params.delete("fields");
    params.set("terms", terms.join(","));
    if (skillNames.length > 0) {
      params.set("skills", skillNames.join(","));
    } else {
      params.delete("skills");
    }
    if (countryCode) params.set("country", countryCode);
    params.delete("page");

    navigate(hrefFor(params));
  }

  function activateLatest() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("view");
    params.delete("fields");
    params.delete("terms");
    params.delete("skills");
    params.delete("page");

    navigate(hrefFor(params));
  }

  if (!hydrated || !skillsHydrated) {
    return <div className="h-8 w-52" aria-hidden="true" />;
  }

  return (
    <div
      aria-busy={isPending}
      className={cn(
        "flex flex-wrap items-center justify-between gap-2",
        isPending && "pointer-events-none cursor-progress opacity-70",
      )}
    >
      {isPending && (
        <span className="sr-only" role="status">
          Updating your feed…
        </span>
      )}
      <div
        role="group"
        aria-label="Feed view"
        className="inline-flex items-center rounded-md border border-border bg-muted p-1"
      >
        <button
          type="button"
          aria-pressed={isForYou}
          disabled={isPending}
          onClick={activateForYou}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] disabled:cursor-wait",
            isForYou
              ? "bg-background text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Sparkles className="size-3.5" aria-hidden="true" />
          For You
        </button>
        <button
          type="button"
          aria-pressed={!isForYou}
          disabled={isPending}
          onClick={activateLatest}
          className={cn(
            "rounded-sm px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] disabled:cursor-wait",
            !isForYou
              ? "bg-background text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          Latest
        </button>
      </div>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={isPending}
        onClick={requestOnboarding}
      >
        <Pencil aria-hidden="true" />
        Edit interests
      </Button>
    </div>
  );
}
