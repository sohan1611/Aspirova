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
    <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-secondary/30 px-4 py-3">
      <p className="min-w-0 flex-1 text-sm leading-6 text-muted-foreground">
        Studying something specific? Tell us your field and we&apos;ll put the most relevant roles first.
      </p>
      <Button type="button" variant="outline" size="sm" onClick={requestOnboarding}>
        Personalise
      </Button>
      <Button type="button" variant="ghost" size="icon" aria-label="Dismiss" onClick={markOnboardingComplete}>
        <X className="size-4" aria-hidden="true" />
      </Button>
    </div>
  );
}
