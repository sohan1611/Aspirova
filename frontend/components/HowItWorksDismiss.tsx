"use client";

import { HOW_IT_WORKS_STORAGE_KEY } from "@/lib/howItWorks";

export default function HowItWorksDismiss({ icon = false }: { icon?: boolean }) {
  function dismiss() {
    try {
      localStorage.setItem(HOW_IT_WORKS_STORAGE_KEY, "1");
    } catch {
      // Dismiss for this document even when storage is unavailable.
    }
    document.documentElement.setAttribute("data-hiw-dismissed", "");

    const target = document.querySelector<HTMLElement>(
      '#feed-search input:not(:disabled), input#feed-search:not(:disabled)',
    ) ?? document.getElementById("signed-out-hero-title");
    target?.focus({ preventScroll: true });
  }

  return (
    <button
      type="button"
      onClick={dismiss}
      aria-label={icon ? "Dismiss how Aspirova works" : undefined}
      className="inline-flex h-6 min-w-6 shrink-0 cursor-pointer items-center justify-center rounded px-1 text-xs font-semibold text-primary hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      {icon ? <span aria-hidden="true" className="text-lg leading-none">×</span> : "Got it"}
    </button>
  );
}
