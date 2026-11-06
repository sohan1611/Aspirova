"use client";

import HoverPrefetchLink from "@/components/HoverPrefetchLink";
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
      className="auth-collapse-while-pending border-b border-border py-6 sm:py-10"
    >
      <div className="max-w-4xl">
        <p className="eyebrow text-primary">Est. 2026 · The Opportunity Almanac</p>
        <h1
          id="signed-out-hero-title"
          className="mt-3 max-w-3xl font-serif text-[1.875rem] font-bold leading-tight text-foreground sm:mt-4 sm:text-4xl"
        >
          Every opportunity. One place.
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:mt-4 sm:text-base sm:leading-relaxed">
          An almanac of internships, jobs, fellowships and research programmes, indexed daily from
          across the web — so you never miss the one that mattered.
        </p>

        <p className="mt-6 hidden max-w-3xl border-l border-border pl-4 text-sm leading-relaxed text-muted-foreground sm:block">
          We index opportunities from company career pages — including Greenhouse, Lever, Ashby
          and SmartRecruiters — plus public job boards, curated competitions, hackathons and research
          fellowships, always linking you to the original listing.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2 sm:mt-7">
          <HeaderAuth triggerLabel="Create a free account" />
          <Button variant="ghost" size="sm" asChild>
            <HoverPrefetchLink href="#feed-search">Browse below ↓</HoverPrefetchLink>
          </Button>
        </div>
      </div>
    </section>
  );
}
