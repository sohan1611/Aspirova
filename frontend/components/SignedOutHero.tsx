"use client";

import Link from "next/link";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/useSession";

export default function SignedOutHero() {
  const session = useSession();

  if (session) {
    return null;
  }

  return (
    <section
      aria-labelledby="signed-out-hero-title"
      className="border-b border-border py-10 sm:py-14"
    >
      <div className="max-w-4xl">
        <p className="eyebrow text-heritage">Est. 2026 · The Opportunity Almanac</p>
        <h1
          id="signed-out-hero-title"
          className="mt-4 max-w-3xl text-3xl font-semibold leading-tight text-foreground sm:text-4xl"
        >
          Every opportunity. One place.
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground">
          An almanac of internships, jobs, fellowships and hidden roles, indexed daily from
          across the web — so you never miss the one that mattered.
        </p>

        <p className="mt-6 max-w-3xl border-l border-border pl-4 text-sm leading-relaxed text-muted-foreground">
          We index opportunities from company career pages — including Greenhouse, Lever, Ashby
          and SmartRecruiters — plus curated competitions, hackathons and research fellowships,
          always linking you to the original source.
        </p>

        <div className="mt-7 flex flex-wrap items-center gap-2">
          <HeaderAuth triggerLabel="Create a free account" />
          <Button variant="ghost" size="sm" asChild>
            <Link href="#feed-search">Browse below ↓</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
