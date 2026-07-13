"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useId, useState, useSyncExternalStore, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CountryPicker } from "@/components/CountryPicker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getCountry } from "@/lib/countries";
import {
  FIELDS,
  OPEN_ONBOARDING_EVENT,
  type InterestFieldKey,
  useInterests,
} from "@/lib/interests";
import { cn } from "@/lib/utils";

const COUNTRY_STORAGE_KEY = "aspirova.country";
const COUNTRY_EVENT = "aspirova:country-change";
const ONBOARDED_STORAGE_KEY = "aspirova.onboarded";
const ONBOARDED_EVENT = "aspirova:onboarded-change";

let inMemoryCountryCode: string | null = null;
let inMemoryOnboardingComplete = false;

function readStoredCountryCode(): string | null {
  try {
    return window.localStorage.getItem(COUNTRY_STORAGE_KEY);
  } catch {
    return inMemoryCountryCode;
  }
}

function storeCountryCode(code: string): void {
  inMemoryCountryCode = code;

  try {
    window.localStorage.setItem(COUNTRY_STORAGE_KEY, code);
  } catch {
    // Keep the rest of onboarding usable when persistent storage is unavailable.
  }
  window.dispatchEvent(new Event(COUNTRY_EVENT));
}

function subscribeToCountry(onStoreChange: () => void): () => void {
  window.addEventListener(COUNTRY_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(COUNTRY_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function hasCompletedOnboarding(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDED_STORAGE_KEY) === "true";
  } catch {
    return inMemoryOnboardingComplete;
  }
}

function subscribeToOnboarding(onStoreChange: () => void): () => void {
  window.addEventListener(ONBOARDED_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(ONBOARDED_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function markOnboardingComplete(): void {
  inMemoryOnboardingComplete = true;

  try {
    window.localStorage.setItem(ONBOARDED_STORAGE_KEY, "true");
  } catch {
    // A later visit can ask again if storage is unavailable.
  }
  window.dispatchEvent(new Event(ONBOARDED_EVENT));
}

function getServerCountryCode(): string | null {
  return null;
}

function getServerOnboardingState(): boolean {
  return false;
}

export default function OnboardingDialog() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { fields, hasStoredInterests, hydrated, setFields } = useInterests();
  const storedCountryCode = useSyncExternalStore(
    subscribeToCountry,
    readStoredCountryCode,
    getServerCountryCode,
  );
  const onboarded = useSyncExternalStore(
    subscribeToOnboarding,
    hasCompletedOnboarding,
    getServerOnboardingState,
  );
  const [requestedOpen, setRequestedOpen] = useState(false);
  const [draftFields, setDraftFields] = useState<InterestFieldKey[] | null>(null);
  const [draftCountryCode, setDraftCountryCode] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const interestsLabelId = useId();

  useEffect(() => {
    function handleOpenRequest() {
      setRequestedOpen(true);
    }

    window.addEventListener(OPEN_ONBOARDING_EVENT, handleOpenRequest);
    return () => window.removeEventListener(OPEN_ONBOARDING_EVENT, handleOpenRequest);
  }, []);

  const selectedFields = draftFields ?? fields;
  const selectedCountryCode = draftCountryCode ?? storedCountryCode;
  const selectedCountry = getCountry(selectedCountryCode);
  const isFirstRun = hydrated && !hasStoredInterests && !onboarded;
  const open = hydrated && (isFirstRun || requestedOpen);

  function resetDraft() {
    setDraftFields(null);
    setDraftCountryCode(null);
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setRequestedOpen(true);
      return;
    }

    setRequestedOpen(false);
    resetDraft();

    if (isFirstRun) markOnboardingComplete();
  }

  function toggleField(field: InterestFieldKey) {
    setDraftFields((current) => {
      const currentFields = current ?? fields;
      return currentFields.includes(field)
        ? currentFields.filter((currentField) => currentField !== field)
        : [...currentFields, field];
    });
  }

  function handleSkip() {
    markOnboardingComplete();
    setRequestedOpen(false);
    resetDraft();
  }

  function handleShowFeed() {
    setFields(selectedFields);
    if (selectedCountry) storeCountryCode(selectedCountry.code);
    markOnboardingComplete();
    setRequestedOpen(false);
    resetDraft();

    const params = new URLSearchParams(searchParams.toString());
    params.delete("q");
    params.set("view", "foryou");
    params.set("fields", selectedFields.join(","));
    if (selectedCountry) params.set("country", selectedCountry.code);
    params.delete("page");
    const query = params.toString();

    startTransition(() => {
      router.push(query ? `/?${query}` : "/");
    });
  }

  if (!hydrated) return null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[min(44rem,calc(100vh-2rem))] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <p className="eyebrow">A more useful starting point</p>
          <DialogTitle className="font-serif text-2xl">Tell us what you&apos;re into</DialogTitle>
          <DialogDescription>
            Pick the areas you want to explore and we&apos;ll surface the most relevant
            opportunities first.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          <section aria-labelledby={interestsLabelId} className="space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              <p id={interestsLabelId} className="text-sm font-medium">
                Your interests
              </p>
              <span className="text-xs text-muted-foreground">Choose as many as you like</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2" role="group" aria-labelledby={interestsLabelId}>
              {FIELDS.map((field) => {
                const isSelected = selectedFields.includes(field.key);

                return (
                  <button
                    key={field.key}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => toggleField(field.key)}
                    className={cn(
                      "flex min-h-10 items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isSelected
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
                    )}
                  >
                    <span>{field.label}</span>
                    <span
                      aria-hidden="true"
                      className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded-full border text-[0.625rem] leading-none",
                        isSelected
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-muted-foreground/50",
                      )}
                    >
                      {isSelected ? "✓" : null}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="space-y-3" aria-labelledby="onboarding-country-label">
            <div>
              <p id="onboarding-country-label" className="text-sm font-medium">
                Where are you based?
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                We&apos;ll use this for local opportunities and location filters.
              </p>
            </div>
            <CountryPicker value={selectedCountryCode} onSelect={setDraftCountryCode}>
              <Button type="button" variant="outline" className="w-full justify-between sm:w-auto">
                <span className="flex min-w-0 items-center gap-2">
                  <span aria-hidden="true">{selectedCountry?.flag ?? "🌍"}</span>
                  <span className="truncate">{selectedCountry?.name ?? "Choose your country"}</span>
                </span>
                <ChevronDown aria-hidden="true" />
              </Button>
            </CountryPicker>
          </section>
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={handleSkip} disabled={isPending}>
            Skip for now
          </Button>
          <Button type="button" onClick={handleShowFeed} disabled={isPending}>
            Show my feed
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
