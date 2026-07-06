"use client";

import { FileSearch, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
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
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    getResumeMatches(accessToken)
      .then((items) => {
        if (cancelled) return;
        setMatches(items);
        setAccessState("pro");
        setCheckedAccessToken(accessToken);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (isProFeatureRequiredError(error)) {
          setAccessState("upsell");
          setMatches(null);
          setCheckedAccessToken(accessToken);
          return;
        }

        setAccessState("pro");
        setCheckedAccessToken(accessToken);
        toast.error("We couldn't load your matches. Please try again.");
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;

    const normalizedResume = resumeText.trim();
    if (!normalizedResume) {
      toast.error("Paste your resume before finding matches.");
      return;
    }

    setSubmitting(true);
    try {
      const { version } = await uploadResume(normalizedResume, accessToken);
      const items = await getResumeMatches(accessToken);
      setMatches(items);
      toast.success("Resume updated", {
        description: `Version ${version} is now powering your matches.`,
      });
    } catch (error: unknown) {
      if (isProFeatureRequiredError(error)) {
        setAccessState("upsell");
        setMatches(null);
      } else {
        toast.error("We couldn't update your matches. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-12">
      <div className="mx-auto max-w-2xl text-center">
        <Badge variant="secondary">
          <Sparkles aria-hidden="true" />
          Pro
        </Badge>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-foreground">
          Resume Match
        </h1>
        <p className="mt-2 text-muted-foreground">
          Turn your experience into a focused shortlist of opportunities ranked by fit.
        </p>
      </div>

      <div className="mt-10">
        {!session ? (
          <SignedOutCard />
        ) : checkedAccessToken !== accessToken ? (
          <CheckingCard />
        ) : accessState === "upsell" ? (
          <UpsellCard />
        ) : (
          <ProResumeContent
            resumeText={resumeText}
            setResumeText={setResumeText}
            submitting={submitting}
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
    <Card className="mx-auto max-w-xl text-center">
      <CardHeader>
        <FileSearch className="mx-auto size-8 text-primary" aria-hidden="true" />
        <CardTitle className="text-xl">Sign in to match your resume</CardTitle>
        <CardDescription>
          Use your Aspirova account to save your resume profile and see personalized matches.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center">
        <HeaderAuth />
      </CardFooter>
    </Card>
  );
}

function CheckingCard() {
  return (
    <Card className="mx-auto max-w-xl text-center" role="status" aria-live="polite">
      <CardContent className="flex flex-col items-center gap-3 py-6">
        <Loader2 className="size-6 animate-spin text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">Loading your Resume Match workspace…</p>
      </CardContent>
    </Card>
  );
}

function UpsellCard() {
  return (
    <Card className="mx-auto max-w-xl text-center">
      <CardHeader>
        <Badge className="mx-auto">Pro feature</Badge>
        <CardTitle className="text-xl">Unlock matches built around your experience</CardTitle>
        <CardDescription>
          Resume Match is included with Pro. Upgrade to rank Aspirova opportunities against
          your skills, education, and goals.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center">
        <Button asChild>
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
  matches,
  onSubmit,
}: {
  resumeText: string;
  setResumeText: (value: string) => void;
  submitting: boolean;
  matches: MatchItem[] | null;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="grid gap-10">
      <Card className="mx-auto w-full max-w-2xl">
        <CardHeader>
          <CardTitle>Tell us what you bring</CardTitle>
          <CardDescription>
            Paste the text from your resume. Submitting again creates a new version and refreshes
            your ranking.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="resume-text">Resume text</Label>
              <Textarea
                id="resume-text"
                name="resume_text"
                required
                rows={12}
                value={resumeText}
                onChange={(event) => setResumeText(event.target.value)}
                placeholder="Paste your education, experience, projects, and skills here…"
                aria-describedby="resume-text-help"
              />
              <p id="resume-text-help" className="text-xs text-muted-foreground">
                Include the details you want Aspirova to use when ranking opportunities.
              </p>
            </div>
            <Button type="submit" disabled={submitting} className="w-full sm:w-fit">
              {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
              {submitting ? "Finding matches…" : "Find my matches"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {matches !== null && <MatchesList matches={matches} />}
    </div>
  );
}

function MatchesList({ matches }: { matches: MatchItem[] }) {
  return (
    <section aria-labelledby="matches-heading">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 id="matches-heading" className="text-2xl font-bold tracking-tight text-foreground">
            Matches for you
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Ranked from the experience and skills in your latest resume.
          </p>
        </div>
        {matches.length > 0 && <Badge variant="outline">{matches.length} results</Badge>}
      </div>

      {matches.length === 0 ? (
        <Card className="mt-5 text-center">
          <CardHeader>
            <FileSearch className="mx-auto size-8 text-muted-foreground" aria-hidden="true" />
            <CardTitle>No matches yet</CardTitle>
            <CardDescription>
              We&apos;re still enriching opportunities. Check back as the catalog grows.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <ol className="mt-5 grid gap-4">
          {matches.map((match, index) => (
            <li key={match.opportunity.slug} className="grid gap-2">
              <div className="flex items-center justify-between gap-3 px-1">
                <span className="text-sm font-medium text-muted-foreground">
                  #{index + 1}
                </span>
                <Badge>{Math.round(match.score * 100)}% match</Badge>
              </div>
              <OpportunityCard item={match.opportunity} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
