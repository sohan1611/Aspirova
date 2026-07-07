import type { Metadata } from "next";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import { getFeed } from "@/lib/api";

const LIMIT = 20;
const DESCRIPTION =
  "Student internships auto-discovered from public company career pages, " +
  "with each listing linking back to the original source.";
const INTRO =
  "Student internships, auto-discovered from public company career pages; " +
  "Aspirova links out to the original source.";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Internships",
  description: DESCRIPTION,
  alternates: { canonical: "/internships" },
};

interface PageProps {
  searchParams: Promise<{ page?: string }>;
}

export default async function InternshipsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const data = await getFeed({ category: "internship", page, limit: LIMIT });

  return (
    <OpportunityLandingPage
      title="Internships"
      intro={INTRO}
      items={data.items}
      total={data.total}
      page={page}
      limit={LIMIT}
      basePath="/internships"
      currentParams={{ page: params.page }}
    />
  );
}
