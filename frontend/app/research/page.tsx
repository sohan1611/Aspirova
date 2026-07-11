import type { Metadata } from "next";
import ResearchProgramCard from "@/components/ResearchProgramCard";
import { RESEARCH_PROGRAMS } from "@/lib/researchPrograms";

const TITLE = "Research fellowships & internships";
const DESCRIPTION =
  "Explore India's flagship IISc, IIT, NIT and TIFR research internships and fellowships, auto-curated with links to the official source.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/research" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "/research",
  },
};

export default function ResearchPage() {
  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">The research track</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Research fellowships & internships
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Explore India&apos;s flagship institute-run research programs from IISc, the IITs, NITs,
          TIFR and the national science academies. Aspirova links straight to the official
          application page. Timelines are tentative, based on recent cycles — always confirm the
          live dates on the official page.
        </p>
      </header>

      <section
        className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
        aria-label="Flagship research programs"
      >
        {RESEARCH_PROGRAMS.map((program) => (
          <ResearchProgramCard key={program.slug} program={program} />
        ))}
      </section>
    </main>
  );
}
