import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import BookmarkButton from "@/components/BookmarkButton";
import { getOpportunity } from "@/lib/api";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    return { title: "Opportunity not found - Aspirova" };
  }

  const companyName = opportunity.company?.name ?? "";
  const title = `${opportunity.title}${companyName ? ` at ${companyName}` : ""} - Aspirova`;
  const description = opportunity.description_raw.slice(0, 160);

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function OpportunityPage({ params }: PageProps) {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    notFound();
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <Link href="/" className="text-sm text-gray-500 underline">
        ← Back to feed
      </Link>

      <h1 className="mt-4 text-2xl font-bold">{opportunity.title}</h1>
      <p className="mt-1 text-gray-600">
        {opportunity.company?.name}
        {opportunity.location ? ` · ${opportunity.location}` : ""}
        {opportunity.is_remote ? " · Remote" : ""}
      </p>

      <div className="mt-4 flex items-center gap-3">
        {/* Always links to the real source - we index and link out, we
            never mirror (Doc 01 sec 7 R1, Doc 04 sec 10). */}
        <a
          href={opportunity.apply_url}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded bg-black px-4 py-2 text-sm text-white"
        >
          Apply at source ↗
        </a>
        <BookmarkButton slug={opportunity.slug} />
      </div>

      {opportunity.deadline && (
        <p className="mt-3 text-sm text-amber-700">
          Deadline: {new Date(opportunity.deadline).toLocaleDateString()}
          {opportunity.deadline_confidence !== "explicit" ? " (estimated)" : ""}
        </p>
      )}

      <article className="mt-6 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">
        {opportunity.description_raw}
      </article>
    </main>
  );
}
