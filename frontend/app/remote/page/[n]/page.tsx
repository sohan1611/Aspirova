import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import {
  LANDING_LIMIT,
  REMOTE_LANDING,
  landingPageMetadata,
  loadLandingPage,
  parsePageSegment,
  totalPagesFor,
} from "@/lib/landing";

// Literal, not the imported LANDING_REVALIDATE, because Next only honours a
// statically analysable value here; keep the two in sync.
export const revalidate = 21600;

// See app/jobs/page/[n]/page.tsx - without this export the `revalidate` above is
// silently ignored and the segment stays per-request.
export async function generateStaticParams(): Promise<{ n: string }[]> {
  return [];
}

interface PageProps {
  params: Promise<{ n: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { n } = await params;
  return landingPageMetadata(REMOTE_LANDING, parsePageSegment(n));
}

export default async function RemotePaginatedPage({ params }: PageProps) {
  const { n } = await params;
  const page = parsePageSegment(n);
  if (page <= 1) {
    redirect(REMOTE_LANDING.basePath);
  }

  const data = await loadLandingPage(REMOTE_LANDING, page);
  if (page > totalPagesFor(data.total)) {
    notFound();
  }

  return (
    <OpportunityLandingPage
      title={REMOTE_LANDING.title}
      intro={REMOTE_LANDING.intro}
      items={data.items}
      total={data.total}
      page={page}
      limit={LANDING_LIMIT}
      basePath={REMOTE_LANDING.basePath}
    />
  );
}
