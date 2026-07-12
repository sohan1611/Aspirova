"use client";

import { Pencil } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSyncExternalStore, useTransition } from "react";
import { CountryPicker } from "@/components/CountryPicker";
import { Button } from "@/components/ui/button";
import { getCountry } from "@/lib/countries";
import { useHydrated } from "@/lib/useHydrated";
import { cn } from "@/lib/utils";

const COUNTRY_STORAGE_KEY = "aspirova.country";
const COUNTRY_EVENT = "aspirova:country-change";

type Scope = "abroad" | "domestic" | "both";

function getScope(value: string | null): Scope {
  if (value === "abroad" || value === "domestic") {
    return value;
  }

  return "both";
}

// localStorage as an external store (the sanctioned pattern — a
// setState-in-effect read triggers cascading renders). Writes dispatch a
// same-tab event so the store re-reads immediately; "storage" covers other tabs.
function readStoredCountryCode(): string | null {
  try {
    return window.localStorage.getItem(COUNTRY_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    return null;
  }
}

function storeCountryCode(code: string): void {
  try {
    window.localStorage.setItem(COUNTRY_STORAGE_KEY, code);
  } catch {
    // Keep the in-session preference even if persistent storage is unavailable.
  }
  window.dispatchEvent(new Event(COUNTRY_EVENT));
}

function subscribeStoredCountry(onChange: () => void): () => void {
  window.addEventListener(COUNTRY_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(COUNTRY_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export default function LocationScope() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isHydrated = useHydrated();
  const [isPending, startTransition] = useTransition();
  const storedCode = useSyncExternalStore(
    subscribeStoredCountry,
    readStoredCountryCode,
    () => null,
  );
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

  function updateScope(scope: Scope, code: string) {
    const params = new URLSearchParams(searchParams.toString());

    if (scope === "both") {
      params.delete("scope");
      params.delete("country");
    } else {
      params.set("scope", scope);
      params.set("country", code);
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
        "flex min-w-0 items-center gap-1",
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
    </div>
  );
}
