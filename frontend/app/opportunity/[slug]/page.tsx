import { Clock, MapPin } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import BookmarkButton from "@/components/BookmarkButton";
import CompanyFavicon from "@/components/CompanyFavicon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getOpportunity } from "@/lib/api";
import { getSourceLabel } from "@/lib/sourceLabel";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
};

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    return { title: "Opportunity not found" };
  }

  // The root layout's title template ("%s - Aspirova") appends the suffix -
  // do not repeat it here, or the <title> doubles up.
  const companyName = opportunity.company?.name ?? "";
  const title = `${opportunity.title}${companyName ? ` at ${companyName}` : ""}`;
  const description = opportunity.description_raw.slice(0, 160);

  return {
    title,
    description,
    // openGraph.title has no automatic template applied (unlike <title>),
    // so the "- Aspirova" suffix is added explicitly here for share
    // previews on Twitter/LinkedIn/etc.
    openGraph: { title: `${title} - Aspirova`, description, type: "website" },
  };
}

export default async function OpportunityPage({ params }: PageProps) {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    notFound();
  }

  const sourceLabel = getSourceLabel(opportunity.apply_url);

  return (
    <main className="mx-auto max-w-prose px-4 py-8">
      <Link
        href="/"
        className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        ← Back to feed
      </Link>

      <div className="mt-4 flex items-start gap-4">
        <CompanyFavicon company={opportunity.company} />
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {opportunity.title}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {opportunity.company?.name}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {opportunity.category && (
          <Badge variant="secondary">
            {CATEGORY_LABEL[opportunity.category] ?? opportunity.category}
          </Badge>
        )}
        {opportunity.is_remote && <Badge variant="secondary">Remote</Badge>}
        {opportunity.location && (
          <Badge variant="outline" className="gap-1 font-normal">
            <MapPin className="h-3 w-3" />
            {opportunity.location}
          </Badge>
        )}
        {sourceLabel && (
          <Badge variant="outline" className="font-normal">
            via {sourceLabel}
          </Badge>
        )}
      </div>

      {opportunity.deadline && (
        <div className="mt-4 inline-flex items-center gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm font-medium text-warning">
          <Clock className="h-4 w-4 shrink-0" />
          Deadline: {new Date(opportunity.deadline).toLocaleDateString()}
          {opportunity.deadline_confidence !== "explicit" ? " (estimated)" : ""}
        </div>
      )}

      <div className="mt-6 flex items-center gap-3">
        {/* Always links to the real source - we index and link out, we
            never mirror (Doc 01 sec 7 R1, Doc 04 sec 10). */}
        <Button size="lg" asChild>
          <a href={opportunity.apply_url} target="_blank" rel="noopener noreferrer">
            Apply at source ↗
          </a>
        </Button>
        <BookmarkButton slug={opportunity.slug} />
      </div>

      <article className="mt-8 leading-relaxed whitespace-pre-wrap text-foreground">
        {opportunity.description_raw}
      </article>
    </main>
  );
}
