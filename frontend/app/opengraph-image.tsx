import { ImageResponse } from "next/og";

export const alt = "Aspirova - Every opportunity. One place.";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

const brandBlue = "#2563eb";
const darkText = "#0f172a";
const mutedText = "#64748b";
const lightBackground = "#f8fafc";
const white = "#ffffff";
const border = "#e2e8f0";

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

export default async function Image() {
  return new ImageResponse(<BrandCard />, size);
}
