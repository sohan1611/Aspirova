"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useHydrated } from "@/lib/useHydrated";

const THEMES = ["light", "dark", "system"] as const;
type ThemeName = (typeof THEMES)[number];

const ICONS: Record<ThemeName, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const hydrated = useHydrated();

  // Theme is only known client-side (next-themes resolves it before
  // paint via an injected script, but React's own render tree doesn't see
  // it until after hydration) - render a same-sized placeholder first to
  // avoid a hydration mismatch or a layout shift once the real icon
  // appears.
  if (!hydrated) {
    return <div className="h-9 w-9" aria-hidden="true" />;
  }

  const current = (theme as ThemeName | undefined) ?? "system";
  const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
  const Icon = ICONS[current];

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Theme: ${current}. Click to switch to ${next}.`}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-card text-foreground transition-colors duration-150 hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <Icon className="h-4 w-4" strokeWidth={2} />
    </button>
  );
}
