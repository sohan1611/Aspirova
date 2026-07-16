import { ImageResponse } from "next/og";

import { getOpportunity } from "../../../lib/api";
import { cleanLocation } from "../../../lib/cleanLocation";

export const alt = "Aspirova opportunity preview";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";
export const dynamic = "force-dynamic";

const brandBlue = "#2563eb";
const darkText = "#0f172a";
const mutedText = "#64748b";
const lightBackground = "#f8fafc";
const white = "#ffffff";
const border = "#e2e8f0";

type RouteParams = {
  slug: string;
};

type RouteProps = {
  params: RouteParams | Promise<RouteParams>;
};

type DataRecord = Record<string, unknown>;

function asRecord(value: unknown): DataRecord | null {
  if (value && typeof value === "object") {
    return value as DataRecord;
  }

  return null;
}

function getString(record: DataRecord | null, keys: string[]): string {
  if (!record) {
    return "";
  }

  for (const key of keys) {
    const value = record[key];

    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return "";
}

function compactText(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();

  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength - 3).trimEnd()}...`;
}

function getCompanyName(opportunity: DataRecord): string {
  const directName = getString(opportunity, [
    "company_name",
    "companyName",
    "organization_name",
    "organizationName",
  ]);

  if (directName) {
    return directName;
  }

  const company = opportunity.company;

  if (typeof company === "string" && company.trim()) {
    return company.trim();
  }

  return getString(asRecord(company), ["name", "company_name", "companyName"]);
}

function getRemoteText(opportunity: DataRecord): string {
  const remoteValue =
    opportunity.remote ?? opportunity.is_remote ?? opportunity.isRemote;

  if (typeof remoteValue === "string" && remoteValue.trim()) {
    return remoteValue.trim();
  }

  if (remoteValue === true) {
    return "Remote";
  }

  const workMode = getString(opportunity, [
    "work_mode",
    "workMode",
    "workplace_type",
    "workplaceType",
  ]);

  if (workMode && workMode.toLowerCase().includes("remote")) {
    return "Remote";
  }

  return "";
}

function getSecondaryLine(opportunity: DataRecord): string {
  const company = getCompanyName(opportunity);
  const location = cleanLocation(
    getString(opportunity, [
      "location",
      "location_text",
      "locationText",
      "location_display",
      "locationDisplay",
    ]),
  );
  const remote = getRemoteText(opportunity);
  const parts = [company, location];

  if (remote && !location.toLowerCase().includes("remote")) {
    parts.push(remote);
  }

  const line = parts.filter(Boolean).join(" - ");

  return line || "Auto-discovered opportunity";
}

function BrandCard() {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        background: lightBackground,
        color: darkText,
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
          background: white,
          border: `1px solid ${border}`,
          borderRadius: 30,
          padding: 56,
        }}
      >
        <div
          style={{
            display: "flex",
            color: brandBlue,
            fontSize: 30,
            fontWeight: 800,
            letterSpacing: 6,
            lineHeight: 1,
          }}
        >
          ASPIROVA
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 22,
            maxWidth: 910,
          }}
        >
          <div
            style={{
              display: "flex",
              fontSize: 78,
              fontWeight: 800,
              lineHeight: 1.04,
              letterSpacing: 0,
            }}
          >
            Aspirova
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 42,
              fontWeight: 700,
              lineHeight: 1.16,
              color: darkText,
              letterSpacing: 0,
            }}
          >
            Every opportunity. One place.
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 30,
              fontWeight: 500,
              lineHeight: 1.28,
              color: mutedText,
              letterSpacing: 0,
            }}
          >
            AI-powered career discovery for students
          </div>
        </div>

        <div
          style={{
            display: "flex",
            width: 136,
            height: 8,
            borderRadius: 999,
            background: brandBlue,
          }}
        />
      </div>
    </div>
  );
}

function OpportunityCard({
  title,
  secondary,
}: {
  title: string;
  secondary: string;
}) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        background: lightBackground,
        color: darkText,
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
          background: white,
          border: `1px solid ${border}`,
          borderRadius: 30,
          padding: 56,
        }}
      >
        <div
          style={{
            display: "flex",
            color: brandBlue,
            fontSize: 30,
            fontWeight: 800,
            letterSpacing: 6,
            lineHeight: 1,
          }}
        >
          ASPIROVA
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 24,
            maxWidth: 980,
          }}
        >
          <div
            style={{
              display: "flex",
              fontSize: 66,
              fontWeight: 800,
              lineHeight: 1.08,
              letterSpacing: 0,
              color: darkText,
            }}
          >
            {title}
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 32,
              fontWeight: 600,
              lineHeight: 1.25,
              color: mutedText,
              letterSpacing: 0,
            }}
          >
            {secondary}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            color: mutedText,
            fontSize: 24,
            fontWeight: 600,
            lineHeight: 1,
          }}
        >
          <div
            style={{
              display: "flex",
              width: 72,
              height: 6,
              borderRadius: 999,
              background: brandBlue,
            }}
          />
          View on Aspirova
        </div>
      </div>
    </div>
  );
}

export default async function Image({ params }: RouteProps) {
  let cardData: { title: string; secondary: string } | null = null;

  try {
    const { slug } = await params;
    const opportunity = await getOpportunity(slug);
    const opportunityRecord = asRecord(opportunity);

    if (opportunityRecord) {
      const title = compactText(
        getString(opportunityRecord, ["title", "name"]) || "Opportunity",
        88,
      );
      const secondary = compactText(getSecondaryLine(opportunityRecord), 92);

      cardData = { title, secondary };
    }
  } catch {
    cardData = null;
  }

  const element = cardData ? (
    <OpportunityCard title={cardData.title} secondary={cardData.secondary} />
  ) : (
    <BrandCard />
  );

  return new ImageResponse(element, size);
}
