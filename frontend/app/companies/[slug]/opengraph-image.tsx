import { ImageResponse } from "next/og";

import { getCompanyPage } from "../../../lib/api";

export const alt = "Aspirova company opportunities preview";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";
export const revalidate = 86400;

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

function getNumber(record: DataRecord | null, keys: string[]): number | null {
  if (!record) {
    return null;
  }

  for (const key of keys) {
    const value = record[key];

    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }

    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);

      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }

  return null;
}

function compactText(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();

  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength - 3).trimEnd()}...`;
}

function getCompanyName(page: DataRecord): string {
  const company = asRecord(page.company);

  return (
    getString(company, ["name", "company_name", "companyName"]) ||
    getString(page, ["name", "company_name", "companyName"]) ||
    "Company"
  );
}

function getOpenRoleCount(page: DataRecord): number {
  const stats = asRecord(page.stats);
  const directCount = getNumber(page, [
    "total",
    "total_count",
    "totalCount",
    "open_roles",
    "openRoles",
    "open_roles_count",
    "openRolesCount",
  ]);
  const statsCount = getNumber(stats, [
    "total",
    "total_count",
    "totalCount",
    "open_roles",
    "openRoles",
    "open_roles_count",
    "openRolesCount",
  ]);
  const opportunities = page.opportunities;

  if (directCount !== null) {
    return directCount;
  }

  if (statsCount !== null) {
    return statsCount;
  }

  if (Array.isArray(opportunities)) {
    return opportunities.length;
  }

  return 0;
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

function CompanyCard({
  companyName,
  countLine,
}: {
  companyName: string;
  countLine: string;
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
              fontSize: 68,
              fontWeight: 800,
              lineHeight: 1.08,
              letterSpacing: 0,
              color: darkText,
            }}
          >
            Opportunities at {companyName}
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 34,
              fontWeight: 600,
              lineHeight: 1.25,
              color: mutedText,
              letterSpacing: 0,
            }}
          >
            {countLine}
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

export default async function Image({ params }: RouteProps) {
  let cardData: { companyName: string; countLine: string } | null = null;

  try {
    const { slug } = await params;
    const companyPage = await getCompanyPage(slug);
    const companyPageRecord = asRecord(companyPage);

    if (companyPageRecord) {
      const companyName = compactText(getCompanyName(companyPageRecord), 54);
      const total = getOpenRoleCount(companyPageRecord);
      const countLine = `${total} open ${total === 1 ? "role" : "roles"}, auto-discovered`;

      cardData = { companyName, countLine };
    }
  } catch {
    cardData = null;
  }

  const element = cardData ? (
    <CompanyCard
      companyName={cardData.companyName}
      countLine={cardData.countLine}
    />
  ) : (
    <BrandCard />
  );

  return new ImageResponse(element, size);
}
