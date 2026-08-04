import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import CompanyOpportunities from "@/components/CompanyOpportunities";
import { getCompanyPage } from "@/lib/api";

const LIMIT = 20;

export const revalidate = 3600;

// Registers the route for on-demand ISR without prerendering any page at build
// time; without this Next leaves a dynamic segment fully per-request.
export async function generateStaticParams(): Promise<{ slug: string; n: string }[]> {
  return [];
}

interface PageProps {
  params: Promise<{ slug: string; n: string }>;
}

function companyPath(slug: string): string {
  return `/companies/${encodeURIComponent(slug)}`;
}

function companyPagePath(slug: string, page: number): string {
  const basePath = companyPath(slug);
  return page <= 1 ? basePath : `${basePath}/page/${page}`;
}

function parsePage(value: string): number {
  return Math.max(1, Number(value) || 1);
}

function totalPagesFor(total: number): number {
  return Math.max(1, Math.ceil(total / LIMIT));
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug, n } = await params;
  const page = parsePage(n);
  const data = await getCompanyPage(slug, page, 1);
  if (!data) {
    notFound();
  }

  if (page > totalPagesFor(data.total)) {
    return {
      title: "Page not found",
      robots: { index: false, follow: false },
    };
  }

  const title = `${data.company.name} opportunities`;
  const description = [
    `Active opportunities at ${data.company.name}, auto-discovered from public company`,
    "career pages",
    "and linked to the original source.",
  ].join(" ");
  const path = companyPagePath(slug, page);

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

export default async function CompanyPaginatedPage({ params }: PageProps) {
  const { slug, n } = await params;
  const page = parsePage(n);
  if (page <= 1) {
    redirect(companyPath(slug));
  }

  const data = await getCompanyPage(slug, page, LIMIT);
  if (!data) {
    notFound();
  }

  if (page > totalPagesFor(data.total)) {
    notFound();
  }

  return <CompanyOpportunities data={data} page={page} slug={slug} />;
}
