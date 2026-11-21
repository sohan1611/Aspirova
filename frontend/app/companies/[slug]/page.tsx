import { withBuildFallback } from "@/lib/buildFallback";
import { CompanyBuildRecovery } from "@/components/BuildListingRecovery";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { addCacheTag } from "@vercel/functions";
import { cache } from "react";
import CompanyOpportunities from "@/components/CompanyOpportunities";
import SourceCompanyDetail from "@/components/SourceCompanyDetail";
import { getCompanyPage } from "@/lib/api";
import { getExternalCompany } from "@/lib/externalCompanies";

const LIMIT = 20;

// Rendered per request, cached by Vercel's CDN via Vercel-CDN-Cache-Control in next.config.ts to preserve the free-plan ISR write budget.
// Responses use the company-<slug> cache tag for CDN purges.
export const dynamic = "force-dynamic";

const loadCompanyPage = cache((slug: string) => getCompanyPage(slug, 1, LIMIT, 0));

interface PageProps {
  params: Promise<{ slug: string }>;
}

function companyPath(slug: string): string {
  return `/companies/${encodeURIComponent(slug)}`;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const external = getExternalCompany(slug);
  if (external) {
    const title = `${external.name} — student roles & flagship programs`;

    return {
      title,
      description: external.note,
      alternates: { canonical: `/companies/${external.slug}` },
      openGraph: {
        title: `${external.name} — Aspirova`,
        description: external.note,
        type: "website",
        url: `/companies/${external.slug}`,
        images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Aspirova" }],
      },
    };
  }

  // Same URL as the page body, so one render makes one API call, not two.
  const result = await withBuildFallback(() => loadCompanyPage(slug), data => data?.items.length ?? 0);
  if (result.status === "failed") return { title: "Company opportunities" };
  const data = result.data;
  if (!data) {
    return { title: "Company not found" };
  }

  const title = `${data.company.name} opportunities`;
  const description = [
    `Active opportunities at ${data.company.name}, auto-discovered from public company`,
    "career pages",
    "and linked to the original source.",
  ].join(" ");
  const path = companyPath(slug);

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      title: `${title} - Aspirova`,
      description,
      type: "website",
      url: path,
      images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Aspirova" }],
    },
  };
}

export default async function CompanyPage({ params }: PageProps) {
  const { slug } = await params;
  if (slug.length <= 120 && /^[a-z0-9][a-z0-9-]*$/.test(slug)) {
    await addCacheTag(`company-${slug}`);
  }
  const external = getExternalCompany(slug);
  if (external) {
    return (
      <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
        <SourceCompanyDetail company={external} />
      </main>
    );
  }

  const result = await withBuildFallback(() => loadCompanyPage(slug), data => data?.items.length ?? 0);
  if (result.status === "failed") return <CompanyBuildRecovery slug={slug} page={1} limit={LIMIT} />;
  const data = result.data;
  if (!data) {
    notFound();
  }

  return <CompanyOpportunities data={data} page={1} slug={slug} />;
}
