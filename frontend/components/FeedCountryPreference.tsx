"use client";

import { getCountry } from "@/lib/countries";
import { setGlobalFeedOrder } from "@/lib/feedPreference";

export default function FeedCountryPreference({
  countryCode,
  preferredCountry,
}: {
  countryCode: string | null;
  preferredCountry: string | null;
}) {
  const country = getCountry(countryCode);
  if (!country) return null;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
      {preferredCountry && <span>Showing {country.name} first</span>}
      <button
        type="button"
        className="underline underline-offset-2 hover:text-foreground"
        onClick={() => setGlobalFeedOrder(Boolean(preferredCountry))}
      >
        {preferredCountry ? "Show global order" : "Show " + country.name + " first"}
      </button>
    </span>
  );
}
