"use client";

import { Pencil } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";
import { CountryPicker } from "@/components/CountryPicker";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { storeCountryCode, useStoredCountryCode } from "@/lib/country";
import { getCountry } from "@/lib/countries";
import { useHydrated } from "@/lib/useHydrated";
import { cn } from "@/lib/utils";

type Scope = "abroad" | "domestic" | "both";

function getScope(value: string | null): Scope {
  if (value === "abroad" || value === "domestic") {
    return value;
  }

  return "both";
}

export default function LocationScope() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isHydrated = useHydrated();
  const [isPending, startTransition] = useTransition();
  const storedCode = useStoredCountryCode();
  const countryCode = storedCode && getCountry(storedCode) ? storedCode : null;

  const requestedScope = getScope(searchParams.get("scope"));
  const storedCountry = countryCode ? getCountry(countryCode) : undefined;
  // A shared URL can carry a different scope country than the local home
  // preference. Reflect the active request rather than showing a mismatched
  // label, but keep the stored preference untouched until the user selects one.
  const scopedCountry =
    requestedScope === "both" ? undefined : getCountry(searchParams.get("country"));
  const activeScope = scopedCountry ? requestedScope : "both";
  const country = scopedCountry ?? storedCountry;
  const includeRemoteAbroad = searchParams.get("remote_abroad") === "true";
  const showRemoteAbroadToggle = Boolean(scopedCountry) && activeScope === "domestic";

  function updateScope(
    scope: Scope,
    code: string,
    remoteAbroad = includeRemoteAbroad,
  ) {
    const params = new URLSearchParams(searchParams.toString());

    if (scope === "both") {
      params.delete("scope");
      params.delete("country");
    } else {
      params.set("scope", scope);
      params.set("country", code);
    }

    if (scope === "domestic" && remoteAbroad) {
      params.set("remote_abroad", "true");
    } else {
      params.delete("remote_abroad");
    }

    params.delete("page");
    const query = params.toString();

    startTransition(() => {
      router.push(query ? `/?${query}` : "/");
    });
  }

  function handleScopeChange(scope: Scope) {
    if (!country) return;

    updateScope(scope, country.code);
  }

  function handleRemoteAbroadChange(checked: boolean) {
    if (!scopedCountry || activeScope !== "domestic") return;

    updateScope("domestic", scopedCountry.code, checked);
  }

  function handleCountrySelect(code: string) {
    const selectedCountry = getCountry(code);
    if (!selectedCountry) return;

    const isInitialSelection = !countryCode;

    storeCountryCode(selectedCountry.code);

    if (isInitialSelection) {
      // A first-time selection opens the feed in the user's country context.
      updateScope("domestic", selectedCountry.code);
    } else if (activeScope !== "both") {
      updateScope(activeScope, selectedCountry.code);
    } else if (searchParams.has("scope") || searchParams.has("country")) {
      updateScope("both", selectedCountry.code);
    }
  }

  if (!isHydrated) {
    return <div className="h-8 w-36" aria-hidden="true" />;
  }

  if (!country) {
    return (
      <CountryPicker value={null} onSelect={handleCountrySelect}>
        <Button type="button" variant="outline" size="sm" disabled={isPending}>
          <span aria-hidden="true">🌍</span>
          Set your country
        </Button>
      </CountryPicker>
    );
  }

  const scopeOptions: { value: Scope; label: React.ReactNode }[] = [
    { value: "abroad", label: "Abroad" },
    {
      value: "domestic",
      label: (
        <>
          <span aria-hidden="true">{country.flag}</span>
          <span className="max-w-28 truncate">{country.name}</span>
        </>
      ),
    },
    { value: "both", label: "Both" },
  ];

  return (
    <div
      aria-busy={isPending}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-x-1 gap-y-2",
        showRemoteAbroadToggle && "w-full sm:w-auto",
        isPending && "pointer-events-none cursor-progress",
      )}
    >
      {isPending && (
        <span className="sr-only" role="status">
          Updating location scope…
        </span>
      )}
      <div
        role="group"
        aria-label={`Location scope for ${country.name}`}
        className="inline-flex max-w-full items-center rounded-md border border-border bg-muted p-1"
      >
        {scopeOptions.map((option) => {
          const isActive = option.value === activeScope;

          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={isActive}
              disabled={isPending}
              onClick={() => handleScopeChange(option.value)}
              className={cn(
                "inline-flex min-w-0 items-center gap-1 whitespace-nowrap rounded-sm px-2.5 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)] disabled:cursor-wait sm:px-3",
                isActive
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      <CountryPicker value={country.code} onSelect={handleCountrySelect}>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          disabled={isPending}
          aria-label={`Change country, currently ${country.name}`}
          title="Change country"
        >
          <Pencil aria-hidden="true" />
        </Button>
      </CountryPicker>

      {showRemoteAbroadToggle && (
        <div className="flex min-w-0 basis-full items-start gap-2 rounded-md border border-border bg-muted px-2.5 py-1.5 sm:basis-auto">
          <input
            id="remote-abroad"
            type="checkbox"
            checked={includeRemoteAbroad}
            disabled={isPending}
            aria-describedby="remote-abroad-hint"
            onChange={(event) => handleRemoteAbroadChange(event.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-border bg-background accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-wait disabled:opacity-50"
          />
          <div className="min-w-0">
            <Label htmlFor="remote-abroad" className="cursor-pointer leading-tight">
              Include remote roles based abroad
            </Label>
            <p id="remote-abroad-hint" className="mt-0.5 text-xs text-muted-foreground">
              Remote roles tied to another country often require work authorization there.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
