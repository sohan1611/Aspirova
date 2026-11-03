import type { Metadata } from "next";
import { cache } from "react";
import { type FeedParams, getFeed } from "@/lib/api";
import { withBuildFallback } from "@/lib/buildFallback";
import { ROLE_OPTIONS } from "@/lib/roleSignalQuery";

export type BrowseCategory = "internship" | "job";
export type BrowseKind = "place" | "role";

export const BROWSE_PLACES = [
  { slug: "bangalore", label: "Bangalore", values: ["Bangalore", "Bengaluru"] },
  { slug: "mumbai", label: "Mumbai", values: ["Mumbai"] },
  { slug: "delhi", label: "Delhi", values: ["Delhi"] },
  { slug: "hyderabad", label: "Hyderabad", values: ["Hyderabad"] },
  { slug: "pune", label: "Pune", values: ["Pune"] },
  { slug: "chennai", label: "Chennai", values: ["Chennai"] },
  { slug: "gurugram", label: "Gurugram", values: ["Gurgaon", "Gurugram"] },
  { slug: "noida", label: "Noida", values: ["Noida"] },
];
export const BROWSE_ROLES = ROLE_OPTIONS;
export const BROWSE_LIMIT = 20;
// Browse pages use the six-hour cache window, so they need no crawl revalidation push.
export const BROWSE_REVALIDATE = 21600;

export interface BrowseConfig {
  category: BrowseCategory;
  kind: BrowseKind;
  slug: string;
  label: string;
  path: string;
  title: string;
  description: string;
  query: FeedParams;
  seeAll: string;
}

function categoryPath(category: BrowseCategory): string {
  return category === "internship" ? "/internships" : "/jobs";
}

function categoryPages(category: BrowseCategory): BrowseConfig[] {
  const base = categoryPath(category);
  const noun = category === "internship" ? "internships" : "jobs";
  const placePages: BrowseConfig[] = BROWSE_PLACES.map((place) => {
    const title = `${category === "internship" ? "Internships" : "Jobs"} in ${place.label}`;
    const search = new URLSearchParams({ category, scope: "domestic", country: "IN" });
    for (const value of place.values) search.append("location", value);
    return {
      category,
      kind: "place",
      slug: place.slug,
      label: place.label,
      path: `${base}/in/${place.slug}`,
      title,
      description: `${title}, auto-discovered from public sources, with links to the original listings.`,
      query: {
        category,
        location: place.values,
        scope: "domestic",
        country: "IN",
        status: "open",
        limit: BROWSE_LIMIT,
      },
      seeAll: `/?${search.toString()}`,
    };
  });
  if (category === "internship") {
    placePages.push({
      category,
      kind: "place",
      slug: "work-from-home",
      label: "Work from home",
      path: `${base}/in/work-from-home`,
      title: "Work from home internships",
      description: "Work from home internships in India, auto-discovered from public sources, with links to the original listings.",
      query: {
        category,
        remote: true,
        scope: "domestic",
        country: "IN",
        status: "open",
        limit: BROWSE_LIMIT,
      },
      seeAll: "/?category=internship&remote=true&scope=domestic&country=IN",
    });
  }
  return [
    ...placePages,
    ...BROWSE_ROLES.map((role): BrowseConfig => ({
      category,
      kind: "role",
      slug: role.value,
      label: role.label,
      path: `${base}/role/${role.value}`,
      title: `${role.label} ${noun}`,
      description: `${role.label} ${noun}, auto-discovered from public sources, with links to the original listings.`,
      query: {
        category,
        role: role.value,
        prefer_country: "IN",
        status: "open",
        limit: BROWSE_LIMIT,
      },
      seeAll: `${base}?role=${role.value}`,
    })),
  ];
}

export const BROWSE_PAGES = [...categoryPages("internship"), ...categoryPages("job")];

export function browsePages(category: BrowseCategory, kind: BrowseKind): BrowseConfig[] {
  return BROWSE_PAGES.filter((page) => page.category === category && page.kind === kind);
}

export function browseConfig(
  category: BrowseCategory,
  kind: BrowseKind,
  slug: string,
): BrowseConfig | undefined {
  return browsePages(category, kind).find((page) => page.slug === slug);
}

export const loadBrowsePage = cache(async (config: BrowseConfig) =>
  withBuildFallback(
    () => getFeed(config.query, BROWSE_REVALIDATE),
    () => ({ items: [], total: 0, page: 1, limit: BROWSE_LIMIT }),
  ),
);

export async function browseMetadata(config: BrowseConfig): Promise<Metadata> {
  const data = await loadBrowsePage(config);
  return {
    title: config.title,
    description: config.description,
    alternates: { canonical: config.path },
    ...(data.total < 5 ? { robots: { index: false } } : {}),
  };
}
