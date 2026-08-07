import type { Metadata } from "next";
import { notFound } from "next/navigation";
import CompanyOpportunities from "@/components/CompanyOpportunities";
import SourceCompanyDetail from "@/components/SourceCompanyDetail";
import { getCompanyPage } from "@/lib/api";
import { getExternalCompany } from "@/lib/externalCompanies";

const LIMIT = 20;

// Sized so each path renders about four times a month; every regeneration is a full render and costs both Fluid CPU and an ISR write.
export const revalidate = 604800;

// Registers the route for on-demand ISR without prerendering any page at build
// time; without this Next leaves a dynamic segment fully per-request.
export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return [];
}

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
      images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Aspirova" }],
    },
  };
}

export default async function CompanyPage({ params }: PageProps) {
  const { slug } = await params;
  const external = getExternalCompany(slug);
  if (external) {
    return (
      <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
        <SourceCompanyDetail company={external} />
      </main>
    );
  }

  const data = await getCompanyPage(slug, 1, LIMIT);
  if (!data) {
    notFound();
  }

  return <CompanyOpportunities data={data} page={1} slug={slug} />;
}
