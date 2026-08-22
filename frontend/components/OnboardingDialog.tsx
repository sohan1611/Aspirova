"use client";

import { ChevronDown } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  useTransition,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
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
import { updateAccount } from "@/lib/api";
import { getCountry } from "@/lib/countries";
import {
  OPEN_ONBOARDING_EVENT,
  storeFieldProfile,
  useFieldProfile,
} from "@/lib/fieldProfile";
import { readStoredSkillNames } from "@/lib/personalizationSkills";
import {
  buildFeedTerms,
  getDivision,
  getStream,
  interestsFor,
  STREAMS,
  type FieldProfile,
} from "@/lib/taxonomy";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

const COUNTRY_STORAGE_KEY = "aspirova.country";
const COUNTRY_EVENT = "aspirova:country-change";
const ONBOARDED_STORAGE_KEY = "aspirova.onboarded";
const ONBOARDED_EVENT = "aspirova:onboarded-change";

type OnboardingStep = "stream" | "division" | "interests";

interface FieldProfileDraft {
  stream: string | null;
  division: string | null;
  interests: string[];
}

const EMPTY_FIELD_PROFILE_DRAFT: FieldProfileDraft = {
  stream: null,
  division: null,
  interests: [],
};

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

function draftFromProfile(profile: FieldProfile): FieldProfileDraft {
  const stream = getStream(profile.stream);
  if (!stream) return EMPTY_FIELD_PROFILE_DRAFT;

  const division =
    profile.divisions.find((divisionKey) => getDivision(stream.key, divisionKey)) ?? null;
  const allowedInterestKeys = new Set(
    division ? interestsFor(stream.key, [division]).map((interest) => interest.key) : [],
  );

  return {
    stream: stream.key,
    division,
    interests: profile.interests.filter((interest) => allowedInterestKeys.has(interest)),
  };
}

function profileFromDraft(draft: FieldProfileDraft): FieldProfile {
  const stream = getStream(draft.stream);
  const division = draft.division && getDivision(stream?.key, draft.division);
  if (!stream || !division) {
    return { stream: null, divisions: [], interests: [] };
  }

  const allowedInterestKeys = new Set(
    interestsFor(stream.key, [division.key]).map((interest) => interest.key),
  );

  return {
    stream: stream.key,
    divisions: [division.key],
    interests: draft.interests.filter((interest) => allowedInterestKeys.has(interest)),
  };
}

function stepAnnouncement(step: OnboardingStep): string {
  if (step === "stream") return "Step 1 of 3: Your field";
  if (step === "division") return "Step 2 of 3: Your specialisation";
  return "Step 3 of 3: Your interests";
}

export default function OnboardingDialog() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const session = useSession();
  const { profile: storedProfile, hasStoredProfile, hydrated } = useFieldProfile();
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
  const [draft, setDraft] = useState<FieldProfileDraft | null>(null);
  const [draftCountryCode, setDraftCountryCode] = useState<string | null>(null);
  const [step, setStep] = useState<OnboardingStep>("stream");
  const [isSaving, setIsSaving] = useState(false);
  const [isPending, startTransition] = useTransition();
  const stepHeadingId = useId();
  const countryLabelId = useId();
  const stepHeadingRef = useRef<HTMLHeadingElement>(null);

  const selectedDraft = draft ?? draftFromProfile(storedProfile);
  const selectedStream = getStream(selectedDraft.stream);
  const selectedDivision = selectedDraft.division
    ? getDivision(selectedStream?.key, selectedDraft.division)
    : undefined;
  const selectedCountryCode = draftCountryCode ?? storedCountryCode;
  const selectedCountry = getCountry(selectedCountryCode);
  const isFirstRun = hydrated && !hasStoredProfile && !onboarded;
  const open = hydrated && (isFirstRun || requestedOpen);
  const isBusy = isSaving || isPending;

  useEffect(() => {
    function handleOpenRequest() {
      setDraft(null);
      setDraftCountryCode(null);
      setStep("stream");
      setRequestedOpen(true);
    }

    window.addEventListener(OPEN_ONBOARDING_EVENT, handleOpenRequest);
    return () => window.removeEventListener(OPEN_ONBOARDING_EVENT, handleOpenRequest);
  }, []);

  useEffect(() => {
    if (!open) return;

    const frame = window.requestAnimationFrame(() => {
      stepHeadingRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, step]);

  function resetDraft() {
    setDraft(null);
    setDraftCountryCode(null);
    setStep("stream");
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

  function handleStreamSelect(streamKey: string) {
    const stream = getStream(streamKey);
    if (!stream) return;

    const streamChanged = selectedDraft.stream !== stream.key;
    const automaticDivision = stream.divisions.length === 1 ? stream.divisions[0]?.key ?? null : null;
    const retainedDivision =
      !streamChanged && selectedDraft.division && getDivision(stream.key, selectedDraft.division)
        ? selectedDraft.division
        : null;
    const division = automaticDivision ?? retainedDivision;
    const allowedInterestKeys = new Set(
      division ? interestsFor(stream.key, [division]).map((interest) => interest.key) : [],
    );

    setDraft({
      stream: stream.key,
      division,
      interests:
        streamChanged || !division
          ? []
          : selectedDraft.interests.filter((interest) => allowedInterestKeys.has(interest)),
    });
    setStep(automaticDivision ? "interests" : "division");
  }

  function handleDivisionSelect(divisionKey: string) {
    if (!selectedStream || !getDivision(selectedStream.key, divisionKey)) return;

    const divisionChanged = selectedDraft.division !== divisionKey;
    const allowedInterestKeys = new Set(
      interestsFor(selectedStream.key, [divisionKey]).map((interest) => interest.key),
    );

    setDraft({
      stream: selectedStream.key,
      division: divisionKey,
      interests: divisionChanged
        ? []
        : selectedDraft.interests.filter((interest) => allowedInterestKeys.has(interest)),
    });
  }

  function toggleInterest(interestKey: string) {
    setDraft((currentDraft) => {
      const nextDraft = currentDraft ?? selectedDraft;
      const interests = nextDraft.interests.includes(interestKey)
        ? nextDraft.interests.filter((currentInterest) => currentInterest !== interestKey)
        : [...nextDraft.interests, interestKey];

      return { ...nextDraft, interests };
    });
  }

  function handleBack() {
    setStep((currentStep) => (currentStep === "interests" ? "division" : "stream"));
  }

  function handleSkip() {
    markOnboardingComplete();
    setRequestedOpen(false);
    resetDraft();
  }

  async function handleShowFeed() {
    const profile = profileFromDraft(selectedDraft);
    if (!profile.stream) {
      setStep("stream");
      return;
    }
    if (profile.divisions.length === 0) {
      setStep("division");
      return;
    }

    setIsSaving(true);
    try {
      storeFieldProfile(profile);

      if (session?.access_token) {
        try {
          await updateAccount(session.access_token, { field_profile: profile });
        } catch {
          toast.error("Saved on this device, but we couldn't sync your interests to your account.");
        }
      }

      markOnboardingComplete();
      setRequestedOpen(false);
      resetDraft();

      const params = new URLSearchParams(searchParams.toString());
      params.delete("q");
      params.delete("fields");
      params.set("view", "foryou");
      const terms = buildFeedTerms(profile, readStoredSkillNames());
      if (terms.length > 0) {
        params.set("terms", terms.join(","));
      } else {
        params.delete("terms");
      }
      if (selectedCountry) {
        storeCountryCode(selectedCountry.code);
        params.set("country", selectedCountry.code);
      }
      params.delete("page");
      const query = params.toString();

      startTransition(() => {
        router.push(query ? `/?${query}` : "/", { scroll: false });
      });
    } finally {
      setIsSaving(false);
    }
  }

  if (!hydrated) return null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[min(44rem,calc(100vh-2rem))] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <p className="eyebrow">A more useful starting point</p>
          <DialogTitle className="font-serif text-2xl">Tell us what you&apos;re into</DialogTitle>
          <DialogDescription>
            Pick your field and interests and we&apos;ll surface the most relevant opportunities
            first.
          </DialogDescription>
        </DialogHeader>

        <p className="sr-only" aria-live="polite" aria-atomic="true">
          {stepAnnouncement(step)}
        </p>

        <div className="space-y-6">
          {step === "stream" && (
            <section aria-labelledby={stepHeadingId} className="space-y-3">
              <div>
                <h2
                  ref={stepHeadingRef}
                  id={stepHeadingId}
                  tabIndex={-1}
                  className="text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Your field
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Choose the broad area you want to explore.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2" role="group" aria-labelledby={stepHeadingId}>
                {STREAMS.map((stream) => {
                  const isSelected = selectedDraft.stream === stream.key;

                  return (
                    <button
                      key={stream.key}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => handleStreamSelect(stream.key)}
                      className={cn(
                        "flex min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-10",
                        isSelected
                          ? "border-primary bg-primary/10 text-foreground"
                          : "border-border bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
                      )}
                    >
                      <span>{stream.label}</span>
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
          )}

          {step === "division" && (
            <section aria-labelledby={stepHeadingId} className="space-y-3">
              <div>
                <h2
                  ref={stepHeadingRef}
                  id={stepHeadingId}
                  tabIndex={-1}
                  className="text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Your specialisation
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {selectedStream
                    ? `Choose the area within ${selectedStream.label} that fits you best.`
                    : "Choose your field first."}
                </p>
              </div>
              {selectedStream && (
                <div
                  className="grid gap-2 sm:grid-cols-2"
                  role="group"
                  aria-labelledby={stepHeadingId}
                >
                  {selectedStream.divisions.map((division) => {
                    const isSelected = selectedDraft.division === division.key;

                    return (
                      <button
                        key={division.key}
                        type="button"
                        aria-pressed={isSelected}
                        onClick={() => handleDivisionSelect(division.key)}
                        className={cn(
                          "flex min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-10",
                          isSelected
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
                        )}
                      >
                        <span>{division.label}</span>
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
              )}
            </section>
          )}

          {step === "interests" && (
            <>
              <section aria-labelledby={stepHeadingId} className="space-y-3">
                <div>
                  <h2
                    ref={stepHeadingRef}
                    id={stepHeadingId}
                    tabIndex={-1}
                    className="text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Your interests
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Choose as many as you like.
                  </p>
                </div>
                {selectedStream && selectedDivision ? (
                  <div
                    className="grid gap-2 sm:grid-cols-2"
                    role="group"
                    aria-labelledby={stepHeadingId}
                  >
                    {interestsFor(selectedStream.key, [selectedDivision.key]).map((interest) => {
                      const isSelected = selectedDraft.interests.includes(interest.key);

                      return (
                        <button
                          key={interest.key}
                          type="button"
                          aria-pressed={isSelected}
                          onClick={() => toggleInterest(interest.key)}
                          className={cn(
                            "flex min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-10",
                            isSelected
                              ? "border-primary bg-primary/10 text-foreground"
                              : "border-border bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
                          )}
                        >
                          <span>{interest.label}</span>
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
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Choose a specialisation before selecting interests.
                  </p>
                )}
              </section>

              <section className="space-y-3" aria-labelledby={countryLabelId}>
                <div>
                  <p id={countryLabelId} className="text-sm font-medium">
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
                      <span className="truncate">
                        {selectedCountry?.name ?? "Choose your country"}
                      </span>
                    </span>
                    <ChevronDown aria-hidden="true" />
                  </Button>
                </CountryPicker>
              </section>
            </>
          )}
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex flex-wrap gap-2">
            {step !== "stream" && (
              <Button type="button" variant="ghost" onClick={handleBack} disabled={isBusy}>
                Back
              </Button>
            )}
            <Button type="button" variant="ghost" onClick={handleSkip} disabled={isBusy}>
              Skip for now
            </Button>
          </div>
          {step === "division" && (
            <Button
              type="button"
              onClick={() => setStep("interests")}
              disabled={isBusy || !selectedDivision}
            >
              Continue
            </Button>
          )}
          {step === "interests" && (
            <Button type="button" onClick={() => void handleShowFeed()} disabled={isBusy}>
              {isSaving ? "Saving…" : "Show my feed"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
