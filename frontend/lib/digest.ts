import { OPPORTUNITY_CATEGORY_LABELS } from "./opportunityCategory";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface DigestItem {
  kind: "opportunity";
  slug: string;
  title: string;
  company_name: string | null;
  category: string;
  deadline: string | null;
  deadline_precision: string | null;
  deadline_confidence: string | null;
}

export interface DigestSample {
  date: string;
  items: DigestItem[];
  counts_by_category: Record<string, number>;
  empty: boolean;
}

export async function getDigestSample(signal?: AbortSignal): Promise<DigestSample | null> {
  try {
    const response = await fetch(`${API_URL}/digest/sample`, { signal });
    if (!response.ok) return null;
    const sample: DigestSample = await response.json();
    return !sample.empty && sample.items?.length > 0 ? sample : null;
  } catch {
    return null;
  }
}

export function categoryCounts(counts: Record<string, number>): string {
  return Object.entries(counts).map(([category, count]) => {
    let label: string;
    if (category === "removed") label = "removed";
    else if (category === "programme_update") label = `programme update${count === 1 ? "" : "s"}`;
    else {
      const categoryLabel = OPPORTUNITY_CATEGORY_LABELS[category];
      label = categoryLabel ? `${categoryLabel.toLowerCase()}${count === 1 ? "" : "s"}` : category.replaceAll("_", " ");
    }
    return `${count} ${label}`;
  }).join(", ");
}
