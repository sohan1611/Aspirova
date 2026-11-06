"use client";

import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import SaveButton from "@/components/SaveButton";
import { Button } from "@/components/ui/button";
import { getForYou } from "@/lib/api";
import { formatCompensation } from "@/lib/compensation";
import { formatDate } from "@/lib/date";
import { requestOnboarding } from "@/lib/fieldProfile";
import { summarizeLocation } from "@/lib/location";
import { buildFeedTerms, type FieldProfile } from "@/lib/taxonomy";
import type { OpportunityListItem } from "@/lib/types";

type ProfileFeedRequest = { terms: string[]; skills: string[]; limit: number };
type FeedState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; items: OpportunityListItem[] };

export default function ProfileOpportunities({
  profile,
  skillNames,
  accountLoading,
}: {
  profile: FieldProfile;
  /** Persisted names, so edits and quick-check suggestions never trigger requests. */
  skillNames: string[];
  accountLoading: boolean;
}) {
  const [attempt, setAttempt] = useState(0);
  const terms = buildFeedTerms(profile, skillNames);
  const hasSignals = terms.length > 0 || skillNames.length > 0;
  const request: ProfileFeedRequest = { terms, skills: skillNames, limit: 6 };
  const requestKey = JSON.stringify(request);
  const params = new URLSearchParams();
  params.delete("q");
  params.set("view", "foryou");
  params.delete("fields");
  params.set("terms", terms.join(","));
  if (skillNames.length > 0) params.set("skills", skillNames.join(","));
  else params.delete("skills");
  params.delete("page");

  return (
    <section className="min-w-0" aria-labelledby="profile-opportunities-heading">
      <h2 id="profile-opportunities-heading" className="font-serif text-2xl font-bold sm:text-3xl">
        Opportunities for your profile
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        Ranked by your chosen fields and saved skills.
      </p>
      <div className="mt-6">
        {accountLoading ? (
          <ProfileFeedSkeleton />
        ) : !hasSignals ? (
          <div className="rounded-lg border border-border bg-card p-6">
            <p className="text-sm leading-6 text-muted-foreground">
              Pick your fields or add skills to see opportunities for you.
            </p>
            <Button type="button" variant="outline" className="mt-4 min-h-11" onClick={requestOnboarding}>
              Pick your fields
            </Button>
          </div>
        ) : (
          <ProfileFeedResults
            key={`${JSON.stringify(profile)}:${requestKey}:${attempt}`}
            requestKey={requestKey}
            onRetry={() => setAttempt((current) => current + 1)}
          />
        )}
      </div>
      {!accountLoading && hasSignals && (
        <HoverPrefetchLink
          href={`/?${params.toString()}`}
          className="mt-5 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          See all in your For You feed
          <ArrowRight className="size-4 shrink-0" aria-hidden="true" />
        </HoverPrefetchLink>
      )}
    </section>
  );
}

function ProfileFeedResults({ requestKey, onRetry }: { requestKey: string; onRetry: () => void }) {
  const [state, setState] = useState<FeedState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const request: ProfileFeedRequest = JSON.parse(requestKey);
    void getForYou(request).then((data) => {
      if (!cancelled) setState({ status: "loaded", items: data.items });
    }).catch(() => {
      if (!cancelled) setState({ status: "error" });
    });
    return () => { cancelled = true; };
  }, [requestKey]);

  if (state.status === "loading") return <ProfileFeedSkeleton />;
  if (state.status === "error") {
    return (
      <div role="alert" className="rounded-lg border border-border bg-card p-6">
        <p className="text-sm leading-6 text-muted-foreground">Couldn&apos;t load opportunities right now.</p>
        <Button type="button" variant="outline" className="mt-4 min-h-11" onClick={onRetry}>Retry</Button>
      </div>
    );
  }
  if (state.items.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-card p-6 text-sm leading-6 text-muted-foreground">
        Nothing matches yet. Add skills or pick more fields.
      </p>
    );
  }

  return (
    <ol className="grid gap-4">
      {state.items.map((item) => {
        const path = `/opportunity/${item.slug}`;
        const isRole = item.category === "job" || item.category === "internship";
        const detail = isRole ? formatCompensation(item.meta) : item.deadline
          ? `Register by ${formatDate(item.deadline)}${item.deadline_confidence !== "explicit" ? " (estimated)" : ""}`
          : null;
        return (
          <li key={item.slug} className="min-w-0 rounded-lg border border-border border-l-4 border-l-primary/40 bg-card p-5 [overflow-wrap:anywhere] sm:p-6">
            <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 flex-1">
                <h3 className="font-serif text-2xl font-bold">
                  <HoverPrefetchLink href={path} className="inline-flex min-h-11 items-center break-words hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {item.title}
                  </HoverPrefetchLink>
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  {[item.company?.name, summarizeLocation(item.location).short].filter(Boolean).join(" · ")}
                </p>
                {detail && <p className="mt-3 text-sm text-muted-foreground">{detail}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-3 sm:flex-col sm:items-stretch">
                <Button asChild className="min-h-11">
                  <HoverPrefetchLink href={path}>View<ArrowRight className="size-4" aria-hidden="true" /></HoverPrefetchLink>
                </Button>
                <SaveButton slug={item.slug} title={item.title} className="min-h-11 min-w-11 sm:w-full" />
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function ProfileFeedSkeleton() {
  return (
    <div role="status" aria-label="Loading opportunities for your profile" className="grid gap-4">
      {[0, 1, 2].map((row) => (
        <div key={row} aria-hidden="true" className="min-h-36 animate-pulse space-y-4 rounded-lg border border-border border-l-4 border-l-primary/40 bg-card p-6">
          <div className="h-6 w-3/4 rounded bg-muted" />
          <div className="h-4 w-1/2 rounded bg-muted" />
          <div className="h-4 w-1/3 rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}
