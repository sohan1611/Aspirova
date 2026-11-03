import { ImageResponse } from "next/og";
import GenericImage from "@/app/opengraph-image";
import { getOpportunity } from "@/lib/api";
import { formatCompensation } from "@/lib/compensation";
import { formatPrizePool } from "@/lib/competition";
import { formatDate } from "@/lib/date";
import { isDeadlinePast } from "@/lib/deadline";
import type { OpportunityDetail } from "@/lib/types";

export const alt = "Opportunity on Aspirova";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const revalidate = 86400;

// Register on-demand ISR without rendering every listing during the build.
export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return [];
}

const CATEGORY_LABELS: Record<string, string> = {
  internship: "Internship",
  job: "Job",
  hackathon: "Hackathon",
  competition: "Competition",
  scholarship: "Scholarship",
};

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  let opportunity: OpportunityDetail | null;
  try {
    const { slug } = await params;
    opportunity = await getOpportunity(slug, 86400);
  } catch {
    return GenericImage();
  }
  if (!opportunity) return GenericImage();

  const isRole = opportunity.category === "job" || opportunity.category === "internship";
  // The bundled OG font does not guarantee a rupee glyph.
  const pay = (isRole ? formatCompensation(opportunity.meta) : formatPrizePool(opportunity.meta))
    ?.replaceAll("₹", "INR ");
  const open = !opportunity.is_stale && !opportunity.is_hidden &&
    !opportunity.closed_at && (!opportunity.deadline || !isDeadlinePast(opportunity.deadline));
  const title = opportunity.title.length > 150
    ? `${opportunity.title.slice(0, 147).trimEnd()}...`
    : opportunity.title;

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        background: "#f8fafc",
        color: "#0f172a",
        padding: 54,
        fontFamily: "Inter, Arial, sans-serif",
      }}
    >
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#ffffff",
          border: "1px solid #e2e8f0",
          borderRadius: 30,
          padding: 48,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", color: "#2563eb", fontSize: 30, fontWeight: 800, letterSpacing: 6 }}>
            ASPIROVA
          </div>
          <div style={{ display: "flex", color: "#64748b", fontSize: 26 }}>
            {CATEGORY_LABELS[opportunity.category ?? ""] ?? "Opportunity"}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div
            style={{
              display: "block",
              fontSize: 52,
              fontWeight: 800,
              lineHeight: 1.12,
              lineClamp: 3,
              overflow: "hidden",
              textOverflow: "ellipsis",
              maxHeight: 175,
              overflowWrap: "break-word",
            }}
          >
            {title.replaceAll("₹", "INR ")}
          </div>
          <div
            style={{
              display: "block",
              fontSize: 30,
              color: "#64748b",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {opportunity.company?.name.replaceAll("₹", "INR ") ?? ""}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, fontSize: 26 }}>
          {pay && (
            <div style={{ display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {pay}
            </div>
          )}
          {open && opportunity.deadline && (
            <div style={{ display: "flex", color: "#64748b" }}>
              Apply by {formatDate(opportunity.deadline)}
            </div>
          )}
          <div style={{ display: "flex", width: 136, height: 8, borderRadius: 999, background: "#2563eb", marginTop: 6 }} />
        </div>
      </div>
    </div>,
    {
      ...size,
      // ImageResponse defaults to max-age=0, which live on Vercel went stale within
      // seconds, so a request could re-render the image. Keep it at the CDN for a day.
      headers: {
        "Cache-Control": "public, max-age=0, s-maxage=86400, stale-while-revalidate=604800",
        "Vercel-CDN-Cache-Control": "max-age=86400, stale-while-revalidate=604800",
      },
    },
  );
}
