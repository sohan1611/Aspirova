"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useHydrated } from "@/lib/useHydrated";
import { cn } from "@/lib/utils";

const THEMES = [
  { key: "light", label: "Light", Icon: Sun },
  { key: "dark", label: "Dark", Icon: Moon },
  { key: "system", label: "System", Icon: Monitor },
] as const;

export default function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const hydrated = useHydrated();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-2xl">Appearance</CardTitle>
        <CardDescription>
          Choose how Aspirova looks on this device.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          role="group"
          aria-label="Color theme"
          className="grid gap-3 sm:grid-cols-3"
        >
          {THEMES.map(({ key, label, Icon }) => {
            const active = hydrated && theme === key;

            return (
              <button
                key={key}
                type="button"
                aria-pressed={active}
                onClick={() => setTheme(key)}
                className={cn(
                  "flex items-center gap-3 rounded-lg border p-4 text-left outline-none transition-all duration-200 ease-premium hover:-translate-y-0.5 hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                  active
                    ? "border-primary bg-primary/10 text-foreground shadow-sm"
                    : "border-border bg-background/50 text-muted-foreground",
                )}
              >
                <Icon
                  className={cn("size-5", active && "text-primary")}
                  aria-hidden="true"
                />
                <span className="font-medium">{label}</span>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
