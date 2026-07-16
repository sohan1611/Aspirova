// Curated "research track" — India's flagship summer research internships &
// fellowships at IISc, the IITs, NITs, TIFR and the national science academies.
// These are recurring, institute-run programs (not a public feed we can index),
// so — exactly like lib/externalCompanies.ts — we surface honest cards that link
// straight to the official application page. Every applyUrl below was
// fetch-verified live (HTTP 200) on 2026-07-11; timelines are TENTATIVE, based on
// recent cycles — students must always confirm the live cycle on the official
// page. Curated starter set, not exhaustive.

export type ResearchScope = "National" | "Institute";

export interface ResearchProgram {
  slug: string;
  /** Program name, e.g. "SURGE". */
  name: string;
  /** Host institute, e.g. "IIT Kanpur". */
  host: string;
  /** Drives the logo via CompanyFavicon. */
  domain: string;
  scope: ResearchScope;
  /** City / reach, for a subtle location line. */
  location: string;
  eligibility: string;
  /** Tentative window based on recent years — never presented as confirmed. */
  timeline: string;
  /** Months (1-12) the application window is usually open, inclusive. "rolling" = accepts year-round. Omit when genuinely unknown. */
  applyWindow?: { fromMonth: number; toMonth: number } | "rolling";
  stipend?: string;
  /** Verified official application/info page. */
  applyUrl: string;
  /** One-line description of the program. */
  blurb: string;
}

export const RESEARCH_PROGRAMS: ResearchProgram[] = [
  {
    slug: "science-academies-srfp",
    name: "Science Academies' Summer Research Fellowship (SRFP)",
    host: "IAS · INSA · NASI",
    domain: "ias.ac.in",
    scope: "National",
    location: "Placements across India (incl. IISc, IITs, TIFR, national labs)",
    eligibility: "Students & teachers in science and engineering",
    timeline: "Apply usually by ~Jan · fellowship ~May–Jul · results ~Mar–Apr",
    applyWindow: { fromMonth: 1, toMonth: 1 },
    stipend: "Travel + living support",
    applyUrl: "https://webjapps.ias.ac.in/SEP/SummerFellowships.jsp",
    blurb:
      "India's three national science academies place ~2,000 students with Fellow-mentors at IISc, the IITs, TIFR and leading national labs — the main structured route into a top-lab summer.",
  },
  {
    slug: "iisc-summer-research",
    name: "IISc Summer Research Internships",
    host: "IISc Bengaluru",
    domain: "iisc.ac.in",
    scope: "Institute",
    location: "Bengaluru",
    eligibility: "UG & master's students (strong academics, typically CGPA ≥ 8)",
    timeline: "Rolling · projects usually ~May–Jul (2–3 months)",
    applyWindow: "rolling",
    applyUrl: "https://occap.iisc.ac.in/index.php/internships/",
    blurb:
      "India's top-ranked research institute hosts undergraduates for 2–3 month projects — reached via the Science Academies fellowship above plus direct department/lab openings.",
  },
  {
    slug: "iitb-ircc-research-internship",
    name: "IRCC Research Internship Award (RIA)",
    host: "IIT Bombay",
    domain: "iitb.ac.in",
    scope: "Institute",
    location: "Mumbai",
    eligibility: "3rd/4th-yr BE/BTech, MSc, MTech, MCA, Int. MSc",
    timeline: "Full-time ~4–6 months (typically Jan–Jul)",
    stipend: "₹15,000 / month",
    applyUrl: "https://rnd.iitb.ac.in/internship_ircc",
    blurb:
      "Full-time, faculty-mentored R&D internships on challenging projects aligned with national goals, run by IIT Bombay's Industrial Research & Consultancy Centre.",
  },
  {
    slug: "iitm-summer-fellowship",
    name: "Summer Fellowship Programme (SFP)",
    host: "IIT Madras",
    domain: "iitm.ac.in",
    scope: "Institute",
    location: "Chennai",
    eligibility: "Non-IIT UG (3rd yr) & PG students across disciplines",
    timeline: "Two months on-campus ~May–Jul · apply usually ~Feb–Mar",
    applyWindow: { fromMonth: 2, toMonth: 3 },
    stipend: "₹15,000 / month",
    applyUrl: "https://ssp.iitm.ac.in/summer-fellowship-registration",
    blurb:
      "A two-month immersive research fellowship across engineering, sciences, humanities and management for high-performing students from other institutes.",
  },
  {
    slug: "iitk-surge",
    name: "SURGE",
    host: "IIT Kanpur",
    domain: "iitk.ac.in",
    scope: "Institute",
    location: "Kanpur",
    eligibility: "UG students — IITK, non-IITK and SAARC (find a faculty mentor)",
    timeline: "~8 weeks, usually ~May–Jul · apply usually in spring",
    applyWindow: { fromMonth: 2, toMonth: 4 },
    applyUrl: "https://surge.iitk.ac.in/",
    blurb:
      "Students-Undergraduate Research Graduate Excellence — IIT Kanpur's flagship summer programme giving undergraduates real research under faculty mentorship since 2006.",
  },
  {
    slug: "nitrkl-summer-internship",
    name: "Summer Internship Programme",
    host: "NIT Rourkela",
    domain: "nitrkl.ac.in",
    scope: "Institute",
    location: "Rourkela",
    eligibility: "BTech, BArch, Int. MSc/MTech, MA, MSc, MBA from across India",
    timeline: "Summer research project, usually ~May–Jul · apply in spring",
    applyWindow: { fromMonth: 2, toMonth: 4 },
    applyUrl: "https://eapplication.nitrkl.ac.in/internship/",
    blurb:
      "A faculty-mentored summer research internship at a leading NIT, open to bright students from institutes across the country.",
  },
  {
    slug: "tifr-vsrp",
    name: "Visiting Students' Research Programme (VSRP)",
    host: "TIFR",
    domain: "tifr.res.in",
    scope: "National",
    location: "Select TIFR centres (Hyderabad, Pune/NCRA, and more)",
    eligibility: "Students in physics, math, CS, biology, chemistry & astronomy",
    timeline: "~May–Jul · apply usually early in the year",
    applyWindow: { fromMonth: 2, toMonth: 4 },
    applyUrl: "https://www.tifr.res.in/academics/summer_program.php",
    blurb:
      "TIFR introduces talented students to frontier research across the sciences through project work at its centres (offerings vary by campus each year).",
  },
];

/**
 * Whether a programme's usual application window includes the supplied month.
 * Unknown and rolling windows remain open so tentative timelines never imply a
 * programme is closed.
 */
export function isApplyWindowLikelyOpen(
  program: ResearchProgram,
  now = new Date(),
): boolean {
  const { applyWindow } = program;

  if (!applyWindow || applyWindow === "rolling") {
    return true;
  }

  const month = now.getMonth() + 1;
  const { fromMonth, toMonth } = applyWindow;

  return fromMonth <= toMonth
    ? month >= fromMonth && month <= toMonth
    : month >= fromMonth || month <= toMonth;
}

// Search intent: whole-word tokens that mean "show the research track". Kept
// conservative so broad queries like "internship" alone don't trigger it.
const _RESEARCH_TOKENS = new Set([
  "research",
  "fellowship",
  "fellowships",
  "srfp",
  "surge",
  "vsrp",
  "sfp",
  "ria",
  "iisc",
  "iit",
  "iits",
  "nit",
  "nits",
  "tifr",
  "iiser",
  "iisers",
  "ias",
  "insa",
  "nasi",
]);

/** True when a search query signals interest in the research track. */
export function matchesResearchIntent(query: string | null | undefined): boolean {
  if (!query) return false;
  const q = query.toLowerCase();
  if (q.includes("research intern") || q.includes("summer research")) return true;
  const tokens = q.split(/[^a-z0-9]+/).filter(Boolean);
  return tokens.some((token) => _RESEARCH_TOKENS.has(token));
}
