import type { Metadata } from "next";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import { getFeed } from "@/lib/api";

const LIMIT = 20;
const DESCRIPTION =
  "Remote internships and jobs auto-discovered from public company career pages, " +
  "with each listing linking back to the original source.";
const INTRO =
  "Remote opportunities, auto-discovered from public company career pages; " +
  "Aspirova links out to the original source.";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Remote opportunities",
  description: DESCRIPTION,
  alternates: { canonical: "/remote" },
};

interface PageProps {
  searchParams: Promise<{ page?: string }>;
}

export default async function RemotePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const data = await getFeed({ remote: true, page, limit: LIMIT });

  return (
    <OpportunityLandingPage
      title="Remote opportunities"
      intro={INTRO}
      items={data.items}
      total={data.total}
      page={page}
      limit={LIMIT}
      basePath="/remote"
      currentParams={{ page: params.page }}
    />
  );
}
