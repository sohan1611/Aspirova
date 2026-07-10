"use client";

import { FileSearch, Loader2, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import OpportunityCard from "@/components/OpportunityCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  getResumeMatches,
  isProFeatureRequiredError,
  uploadResume,
} from "@/lib/api";
import type { MatchItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

type AccessState = "pro" | "upsell";

export default function ResumeMatchPage() {
  const session = useSession();
  const accessToken = session?.access_token;
  const [resumeText, setResumeText] = useState("");
  const [matches, setMatches] = useState<MatchItem[] | null>(null);
  const [accessState, setAccessState] = useState<AccessState>("pro");
  const [checkedAccessToken, setCheckedAccessToken] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [submissionError, setSubmissionError] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    getResumeMatches(accessToken)
      .then((items) => {
        if (cancelled) return;
        setMatches(items);
        setAccessState("pro");
        setLoadError(false);
        setSubmissionError(false);
        setCheckedAccessToken(accessToken);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (isProFeatureRequiredError(error)) {
          setAccessState("upsell");
          setMatches(null);
          setLoadError(false);
          setSubmissionError(false);
          setCheckedAccessToken(accessToken);
          return;
        }

        setAccessState("pro");
        setMatches(null);
        setLoadError(true);
        setCheckedAccessToken(accessToken);
        toast.error("We couldn't load your matches. Please try again.");
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, retryNonce]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;

    const normalizedResume = resumeText.trim();
    if (!normalizedResume) {
      toast.error("Paste your resume before finding matches.");
      return;
    }

    setSubmissionError(false);
    setSubmitting(true);
    try {
      const { version } = await uploadResume(normalizedResume, accessToken);
      const items = await getResumeMatches(accessToken);
      setMatches(items);
      setLoadError(false);
      setSubmissionError(false);
      toast.success("Resume updated", {
        description: `Version ${version} is now powering your matches.`,
      });
    } catch (error: unknown) {
      if (isProFeatureRequiredError(error)) {
        setAccessState("upsell");
        setMatches(null);
        setLoadError(false);
        setSubmissionError(false);
      } else {
        setSubmissionError(true);
        toast.error("We couldn't update your matches. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <header className="mx-auto max-w-3xl text-center">
        <div className="flex flex-wrap items-center justify-center gap-2.5">
          <p className="eyebrow">Career intelligence</p>
          <Badge variant="heritage">
            <Sparkles aria-hidden="true" />
            Pro
          </Badge>
        </div>
        <h1 className="mt-4 text-3xl font-semibold text-foreground sm:text-4xl">
          Resume Match
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
          Turn your experience into a focused shortlist of opportunities ranked by fit.
        </p>
      </header>

      <div className="mt-10 sm:mt-12">
        {!session ? (
          <SignedOutCard />
        ) : checkedAccessToken !== accessToken ? (
          <CheckingCard />
        ) : loadError ? (
          <LoadErrorCard
            onRetry={() => {
              setLoadError(false);
              setCheckedAccessToken(null);
              setRetryNonce((attempt) => attempt + 1);
            }}
          />
        ) : accessState === "upsell" ? (
          <UpsellCard />
        ) : (
          <ProResumeContent
            resumeText={resumeText}
            setResumeText={setResumeText}
            submitting={submitting}
            submissionError={submissionError}
            matches={matches}
            onSubmit={handleSubmit}
          />
        )}
      </div>
    </main>
  );
}

function SignedOutCard() {
  return (
    <Card className="mx-auto max-w-2xl border-primary/20 text-center shadow-soft-md">
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-primary/20 bg-primary/10 p-3">
          <FileSearch className="size-6 text-primary" aria-hidden="true" />
        </div>
        <p className="eyebrow">Personal matching</p>
        <CardTitle className="font-serif text-2xl leading-tight sm:text-3xl">
          Sign in to match your resume
        </CardTitle>
        <CardDescription className="max-w-lg leading-6">
          Use your Aspirova account to save your resume profile and see personalized matches.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-8">
        <HeaderAuth triggerLabel="Sign in to continue" triggerSize="default" />
      </CardFooter>
    </Card>
  );
}

function CheckingCard() {
  return (
    <Card
      className="mx-auto max-w-2xl border-primary/20 shadow-soft-md"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <CardHeader className="px-5 sm:px-8">
        <p className="eyebrow">Preparing your shortlist</p>
        <CardTitle className="font-serif text-2xl">Loading Resume Match</CardTitle>
        <CardDescription>
          Checking your plan and latest resume profile…
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-5 sm:px-8" aria-hidden="true">
        <div className="h-3 w-24 animate-pulse rounded-full bg-muted" />
        <div className="h-7 w-2/3 animate-pulse rounded-md bg-muted" />
        <div className="h-3 w-full animate-pulse rounded-full bg-muted" />
        <div className="h-3 w-4/5 animate-pulse rounded-full bg-muted" />
        <div className="mt-2 h-9 w-36 animate-pulse rounded-md bg-secondary" />
      </CardContent>
    </Card>
  );
}

function LoadErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <Card
      className="mx-auto max-w-2xl border-primary/20 text-center shadow-soft-md"
      role="alert"
    >
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-border bg-secondary/50 p-3">
          <FileSearch className="size-6 text-primary" aria-hidden="true" />
        </div>
        <p className="eyebrow">Workspace unavailable</p>
        <CardTitle className="font-serif text-2xl leading-tight sm:text-3xl">
          We couldn&apos;t load your matches
        </CardTitle>
        <CardDescription className="max-w-lg leading-6">
          Your resume is still safe. Try the match catalog again in a moment.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-8">
        <Button type="button" onClick={onRetry}>
          <RefreshCw aria-hidden="true" />
          Try again
        </Button>
      </CardFooter>
    </Card>
  );
}

function UpsellCard() {
  return (
    <Card className="mx-auto max-w-2xl border-heritage/25 text-center shadow-soft-md">
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-heritage/20 bg-heritage/10 p-3">
          <Sparkles className="size-6 text-heritage" aria-hidden="true" />
        </div>
        <p className="eyebrow">The Pro shortlist</p>
        <Badge variant="heritage">Pro feature</Badge>
        <CardTitle className="font-serif text-2xl leading-tight sm:text-3xl">
          Unlock matches built around your experience
        </CardTitle>
        <CardDescription className="max-w-lg leading-6">
          Resume Match is included with Pro. Upgrade to rank Aspirova opportunities against
          your skills, education, and goals.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-8">
        <Button asChild size="lg">
          <Link href="/pricing">View Pro pricing</Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

function ProResumeContent({
  resumeText,
  setResumeText,
  submitting,
  submissionError,
  matches,
  onSubmit,
}: {
  resumeText: string;
  setResumeText: (value: string) => void;
  submitting: boolean;
  submissionError: boolean;
  matches: MatchItem[] | null;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);

  return (
    <div className="grid gap-12 sm:gap-14">
      <div className="grid gap-5">
        <Card
          id="resume-workspace"
          className="mx-auto w-full max-w-3xl scroll-mt-24 border-primary/20 shadow-soft-md"
        >
          <CardHeader className="px-5 sm:px-8">
            <p className="eyebrow">Your experience</p>
            <CardTitle className="font-serif text-2xl leading-tight">
              Tell us what you bring
            </CardTitle>
            <CardDescription className="max-w-2xl leading-6">
              Paste the text from your resume. Submitting again creates a new version and refreshes
              your ranking.
            </CardDescription>
          </CardHeader>
          <CardContent className="px-5 sm:px-8">
            <form
              ref={formRef}
              onSubmit={onSubmit}
              className="grid gap-5"
              aria-busy={submitting}
            >
              <div className="grid gap-2.5">
                <Label className="eyebrow" htmlFor="resume-text">
                  Resume text
                </Label>
                <Textarea
                  id="resume-text"
                  name="resume_text"
                  required
                  rows={12}
                  value={resumeText}
                  onChange={(event) => setResumeText(event.target.value)}
                  placeholder="Paste your education, experience, projects, and skills here…"
                  aria-describedby="resume-text-help"
                  className="min-h-72 bg-background/60 px-4 py-3 leading-6 shadow-soft"
                />
                <p id="resume-text-help" className="text-xs leading-5 text-muted-foreground">
                  Include the details you want Aspirova to use when ranking opportunities.
                </p>
              </div>
              <div className="flex border-t border-border pt-5 sm:justify-end">
                <Button
                  type="submit"
                  size="lg"
                  disabled={submitting}
                  className="w-full sm:w-auto"
                >
                  {submitting ? (
                    <Loader2 className="animate-spin" aria-hidden="true" />
                  ) : (
                    <FileSearch aria-hidden="true" />
                  )}
                  {submitting ? "Finding matches…" : "Analyze my resume"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        {submissionError && (
          <SubmissionErrorCard
            submitting={submitting}
            onRetry={() => {
              if (!submitting) formRef.current?.requestSubmit();
            }}
          />
        )}
      </div>

      {matches !== null && <MatchesList matches={matches} />}
    </div>
  );
}

function SubmissionErrorCard({
  submitting,
  onRetry,
}: {
  submitting: boolean;
  onRetry: () => void;
}) {
  return (
    <Card
      className="mx-auto w-full max-w-3xl border-primary/20 shadow-soft-md"
      role="alert"
    >
      <CardHeader className="px-5 sm:px-8">
        <p className="eyebrow">Analysis interrupted</p>
        <CardTitle className="font-serif text-2xl leading-tight">
          We couldn&apos;t refresh your matches
        </CardTitle>
        <CardDescription className="max-w-2xl leading-6">
          Your current shortlist is unchanged. Try analyzing the same resume again.
        </CardDescription>
      </CardHeader>
      <CardFooter className="flex-col items-stretch gap-4 px-5 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p className="text-xs leading-5 text-muted-foreground">
          Your resume text is still ready in the editor above.
        </p>
        <Button
          type="button"
          onClick={onRetry}
          disabled={submitting}
          className="w-full sm:w-auto"
        >
          {submitting ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          {submitting ? "Trying again…" : "Try again"}
        </Button>
      </CardFooter>
    </Card>
  );
}

function MatchesList({ matches }: { matches: MatchItem[] }) {
  return (
    <section aria-labelledby="matches-heading">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Curated shortlist</p>
          <h2 id="matches-heading" className="mt-2 text-2xl font-semibold text-foreground sm:text-3xl">
            Matches for you
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Ranked from the experience and skills in your latest resume.
          </p>
        </div>
        {matches.length > 0 && (
          <Badge variant="outline" className="tnum border-primary/25 bg-primary/10 text-primary">
            {matches.length} {matches.length === 1 ? "match" : "matches"}
          </Badge>
        )}
      </div>

      {matches.length === 0 ? (
        <Card className="mt-6 border-primary/20 text-center shadow-soft-md">
          <CardHeader className="justify-items-center px-5 sm:px-8">
            <div className="mb-1 rounded-xl border border-border bg-secondary/50 p-3">
              <FileSearch className="size-6 text-primary" aria-hidden="true" />
            </div>
            <p className="eyebrow">Catalog watch</p>
            <CardTitle className="font-serif text-2xl leading-tight">
              No strong matches yet
            </CardTitle>
            <CardDescription className="max-w-lg leading-6">
              We&apos;re still enriching opportunities. Check back as the catalog grows.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center px-5 sm:px-8">
            <Button asChild variant="outline">
              <a href="#resume-workspace">Refine your resume</a>
            </Button>
          </CardFooter>
        </Card>
      ) : (
        <ol className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {matches.map((match, index) => (
            <li key={match.opportunity.slug} className="flex h-full min-w-0 flex-col gap-3">
              <div className="flex items-center justify-between gap-3 px-1">
                <span className="eyebrow tnum">
                  Rank {String(index + 1).padStart(2, "0")}
                </span>
                <Badge
                  variant="outline"
                  className="tnum border-primary/25 bg-primary/10 text-primary"
                >
                  {Math.round(match.score * 100)}% fit
                </Badge>
              </div>
              <div className="min-h-0 flex-1">
                <OpportunityCard item={match.opportunity} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
