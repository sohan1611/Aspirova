"use client";

import { X } from "lucide-react";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { requestOnboarding, useFieldProfile } from "@/lib/fieldProfile";
import {
  getServerOnboardingState,
  hasCompletedOnboarding,
  markOnboardingComplete,
  subscribeToOnboarding,
} from "@/lib/onboarding";

export default function PersonalisePrompt() {
  const { hasStoredProfile, hydrated } = useFieldProfile();
  const onboarded = useSyncExternalStore(
    subscribeToOnboarding,
    hasCompletedOnboarding,
    getServerOnboardingState,
  );

  if (!hydrated || hasStoredProfile || onboarded) return null;

  return (
    <div className="relative mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-secondary/30 px-4 py-3 sm:gap-3">
      <p className="min-w-0 basis-full pr-10 text-sm leading-6 text-muted-foreground sm:flex-1 sm:basis-auto sm:pr-0">
        Studying something specific? Tell us your field and we&apos;ll put the most relevant roles first.
      </p>
      <Button type="button" variant="outline" size="sm" onClick={requestOnboarding}>
        Personalise
      </Button>
      <Button type="button" variant="ghost" size="icon" className="absolute right-2 top-2 sm:static" aria-label="Dismiss" onClick={markOnboardingComplete}>
        <X className="size-4" aria-hidden="true" />
      </Button>
    </div>
  );
}
