import { formatDate } from "@/lib/date";
import type { ProgrammeEditionItem } from "@/lib/types";

export const PROGRAMME_CATEGORY_LABELS: Record<string, string> = {
  research_internship: "Research internship",
  fellowship: "Fellowship",
  government_internship: "Government internship",
  open_source: "Open source",
  international_research: "International research",
  corporate_research: "Corporate research",
  recurring_competition: "Recurring competition",
  scholarship: "Scholarship",
  conference: "Conference",
};

export const PROGRAMME_CATEGORIES = Object.entries(PROGRAMME_CATEGORY_LABELS).map(
  ([value, label]) => ({ value, label }),
);

export type ProgrammeStatusTone = "primary" | "neutral";

export interface ProgrammeStatusDisplay {
  text: string;
  tone: ProgrammeStatusTone;
}

function cleanText(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed || null;
}

export function formatProgrammeCategory(category: string): string {
  return PROGRAMME_CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
}

export function programmePath(slug: string): string {
  return `/programme/${encodeURIComponent(slug)}`;
}

export function getProgrammeStatusDisplay(
  edition: ProgrammeEditionItem | null | undefined,
  typicalWindow: string | null | undefined,
): ProgrammeStatusDisplay {
  const windowText = cleanText(typicalWindow);
  if (!edition) {
    return { text: windowText ?? "Window to be confirmed", tone: "neutral" };
  }

  switch (edition.status) {
    case "open":
      return { text: "Open now", tone: "primary" };
    case "announced":
      return {
        text: edition.opens_at ? `Opens ${formatDate(edition.opens_at)}` : "Announced",
        tone: "neutral",
      };
    case "closed":
      return {
        text: windowText
          ? `Closed - next edition expected ${windowText}`
          : "Closed",
        tone: "neutral",
      };
    case "expected":
      return { text: windowText ?? "Expected", tone: "neutral" };
    case "discontinued":
      return { text: "Discontinued", tone: "neutral" };
    default:
      return {
        text: cleanText(edition.status.replace(/_/g, " ")) ?? "Status to be confirmed",
        tone: "neutral",
      };
  }
}
