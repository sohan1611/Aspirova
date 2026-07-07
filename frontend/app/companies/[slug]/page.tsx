import type { Metadata } from "next";
import { notFound } from "next/navigation";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import { getCompanyPage } from "@/lib/api";

const LIMIT = 20;
const INTRO =
  "Auto-discovered from public company career pages; " +
  "Aspirova links out to the original source.";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ page?: string }>;
}

function companyPath(slug: string): string {
  return `/companies/${encodeURIComponent(slug)}`;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const data = await getCompanyPage(slug, 1, 1);
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
    },
  };
}

export default async function CompanyPage({ params, searchParams }: PageProps) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const page = Math.max(1, Number(query.page ?? "1") || 1);
  const data = await getCompanyPage(slug, page, LIMIT);
  if (!data) {
    notFound();
  }

  return (
    <OpportunityLandingPage
      title={`Opportunities at ${data.company.name}`}
      intro={INTRO}
      items={data.items}
      total={data.total}
      page={page}
      limit={LIMIT}
      basePath={companyPath(slug)}
      currentParams={{ page: query.page }}
    />
  );
}
