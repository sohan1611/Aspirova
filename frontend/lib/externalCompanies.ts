// Curated "straight to source" entries for companies that don't expose a public
// job feed we can index (Google, Microsoft, Apple). Instead of showing nothing
// (which reads as "incomplete"), we surface an honest branded card that links to
// their official careers + lists their flagship annual student programs so a
// student knows what recurs and roughly when. Every URL here was fetch-verified
// live (HTTP 200) on 2026-07-11; program dates are TENTATIVE (based on recent
// cycles) — always defer to the official page for the live cycle.

export type ProgramScope = "International" | "India";

export interface FlagshipProgram {
  name: string;
  scope: ProgramScope;
  /** Tentative timeline based on recent years — never presented as confirmed. */
  timeline: string;
  url: string;
}

export interface ExternalCompany {
  slug: string;
  name: string;
  /** Drives the logo via CompanyFavicon. */
  domain: string;
  careersUrl: string;
  careersLabel: string;
  /** Honest, positive framing — a feature, not an apology. */
  note: string;
  programs: FlagshipProgram[];
}

export const EXTERNAL_COMPANIES: ExternalCompany[] = [
  {
    slug: "google",
    name: "Google",
    domain: "google.com",
    careersUrl: "https://www.google.com/about/careers/applications/students/",
    careersLabel: "View student roles on Google Careers",
    note: "Aspirova always links you to the original source. Google posts its student roles only on its own careers site, so we send you straight there — no middleman, no mirrored applications.",
    programs: [
      {
        name: "Google Summer of Code (GSoC)",
        scope: "International",
        timeline: "Applications usually Mar–Apr · coding May–Aug · stipend up to ₹3.5L",
        url: "https://summerofcode.withgoogle.com/",
      },
      {
        name: "GDG Solution Challenge",
        scope: "International",
        timeline: "Usually Mar–Jun · build-with-AI hackathon for student developers",
        url: "https://developers.google.com/community/gdsc-solution-challenge",
      },
      {
        name: "STEP Internship",
        scope: "International",
        timeline: "For 1st/2nd-year students · applications usually in the fall",
        url: "https://www.google.com/about/careers/applications/students/",
      },
      {
        name: "Google Girl Hackathon",
        scope: "India",
        timeline: "For women in engineering · usually early in the year",
        url: "https://www.google.com/about/careers/applications/students/",
      },
    ],
  },
  {
    slug: "microsoft",
    name: "Microsoft",
    domain: "microsoft.com",
    careersUrl: "https://careers.microsoft.com/v2/global/en/students",
    careersLabel: "View student roles on Microsoft Careers",
    note: "Aspirova always links you to the original source. Microsoft lists its student roles only on its own careers site, so we point you straight there — you always apply on the official page.",
    programs: [
      {
        name: "Microsoft Imagine Cup",
        scope: "International",
        timeline: "Season usually Sep→May · MVP round ~Jan · World finals ~Apr–May",
        url: "https://imaginecup.microsoft.com/",
      },
      {
        name: "Microsoft Engage",
        scope: "India",
        timeline: "Mentorship program · registration usually ~Apr · mentorship ~Jun–Jul",
        url: "https://careers.microsoft.com/v2/global/en/students",
      },
      {
        name: "Explore Internship",
        scope: "International",
        timeline: "For 1st/2nd-year students · applications usually in the fall",
        url: "https://careers.microsoft.com/v2/global/en/students",
      },
    ],
  },
  {
    slug: "apple",
    name: "Apple",
    domain: "apple.com",
    careersUrl: "https://www.apple.com/careers/us/students.html",
    careersLabel: "View student roles on Apple Careers",
    note: "Aspirova always links you to the original source. Apple publishes its student roles only on its own careers site, so we send you straight there — every apply goes to Apple directly.",
    programs: [
      {
        name: "Swift Student Challenge",
        scope: "International",
        timeline: "Applications usually ~Feb · results ~late Mar · build an app playground",
        url: "https://developer.apple.com/swift-student-challenge/",
      },
    ],
  },
];

const _BY_KEY = new Map<string, ExternalCompany>();
for (const c of EXTERNAL_COMPANIES) {
  _BY_KEY.set(c.slug, c);
  _BY_KEY.set(c.name.toLowerCase(), c);
}

/** Match a search query to an external company (exact-ish name/slug match). */
export function findExternalCompany(query: string | null | undefined): ExternalCompany | undefined {
  if (!query) return undefined;
  const q = query.trim().toLowerCase();
  if (!q) return undefined;
  return _BY_KEY.get(q) ?? EXTERNAL_COMPANIES.find((c) => c.name.toLowerCase() === q);
}

export function getExternalCompany(slug: string): ExternalCompany | undefined {
  return EXTERNAL_COMPANIES.find((c) => c.slug === slug);
}
