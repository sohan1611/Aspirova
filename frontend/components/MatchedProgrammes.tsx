"use client";

import { useEffect, useState } from "react";
import ProgrammeCard from "@/components/ProgrammeCard";
import { getProgrammes } from "@/lib/api";
import { useFieldProfile } from "@/lib/fieldProfile";
import type { ProgrammeListItem } from "@/lib/types";

export default function MatchedProgrammes() {
  const { profile, hasStoredProfile, hydrated } = useFieldProfile();
  const divisionKey = profile.divisions.join(",");
  const [result, setResult] = useState<{
    divisionKey: string;
    matches: ProgrammeListItem[];
  }>({ divisionKey: "", matches: [] });

  useEffect(() => {
    if (!hydrated || !hasStoredProfile || !divisionKey) {
      return;
    }

    let cancelled = false;
    const selectedDivisions = divisionKey.split(",").filter(Boolean);

    getProgrammes({ divisions: selectedDivisions, limit: 9 })
      .then((data) => {
        if (cancelled) return;
        setResult({
          divisionKey,
          matches: data.items
            .filter((programme) => programme.match_count > 0)
            .slice(0, 6),
        });
      })
      .catch(() => {
        if (!cancelled) setResult({ divisionKey, matches: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [divisionKey, hasStoredProfile, hydrated]);

  const matches = result.divisionKey === divisionKey ? result.matches : [];

  if (!hydrated || !hasStoredProfile || !divisionKey || matches.length === 0) {
    return null;
  }

  return (
    <section className="mt-10" aria-labelledby="matched-programmes-heading">
      <div className="max-w-3xl">
        <h2
          id="matched-programmes-heading"
          className="font-serif text-2xl font-semibold text-foreground sm:text-3xl"
        >
          Matched to your profile
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          Recurring programmes in your selected field, shown with their usual
          windows from the registry.
        </p>
      </div>
      <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {matches.map((programme) => (
          <ProgrammeCard key={programme.slug} programme={programme} />
        ))}
      </div>
    </section>
  );
}
