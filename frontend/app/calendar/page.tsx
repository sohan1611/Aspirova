import type { Metadata } from "next";
import HiringCalendar from "@/components/HiringCalendar";
import { fetchCalendar, parseCalendarParams, todayIST } from "@/lib/hiringCalendar";
import type { CalendarResponse } from "@/lib/hiringCalendar";

export const revalidate = 3600;
export const dynamic = "force-static";
export function generateStaticParams() { return []; }

export const metadata: Metadata = {
  title: "Hiring Calendar",
  description: "Plan application windows for research, government, early-career roles and competitions. Official dates and historical trends are clearly labelled.",
  alternates: { canonical: "/calendar" },
};

export default async function CalendarPage() {
  const query = parseCalendarParams(new URLSearchParams(), todayIST());
  let data: CalendarResponse | null = null;
  try {
    data = await fetchCalendar(query, { next: { revalidate: 3600 } } as RequestInit);
  } catch {
    // Keep the static shell usable while the public API recovers.
  }
  return (
    <main className="mx-auto w-full min-w-0 max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
      <h1 className="font-serif text-3xl font-bold tracking-tight sm:text-4xl">Hiring Calendar</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
        Plan around application openings. A 2027 programme may accept applications in 2026,
        and a 2027 drive may recruit for 2028. The cycle year follows the programme intake.
        All projected months are tentative historical trends unless labelled official.
        A historical watch item becomes open only after an official call is verified.
      </p>
      <details className="mt-4 rounded-lg border border-border bg-card px-4 text-sm">
        <summary className="flex min-h-11 cursor-pointer items-center font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Before you apply
        </summary>
        <div className="space-y-3 pb-4 leading-6 text-muted-foreground">
          <p>Check the current cycle and live status, graduation year and course, country and institution,
            cutoff timezone, campus or direct application route, fees, compensation and visa rules.
            Confirm whether selection offers a role, interview, research project, prize or fellowship.
            Competitions offer different outcomes. Hiring, interviews and PPOs require separate confirmation.</p>
          <p>D. E. Shaw India uses placement-cell applications. Microsoft Explore India eligibility follows
            the specific vacancy. RBI Summer Placement targets the listed postgraduate and integrated streams.
            NICSI is a government-linked services company. DRDO and ISRO calls vary by lab or centre.</p>
          <p>The main Mitacs 2027 call was already closed when checked. PIMS–Mitacs has a separate institution list.
            Verify Google and Adobe roles for India. SIH, Tata Imagination, Schneider Go Green and Imagine Cup
            carry their own competition rules. Pay attention to the original cutoff timezone on overseas calls.
            The calendar uses IST for date boundaries. Last checked records a page check and may accompany an
            unchanged historical estimate.</p>
          <p>Never pay to secure a job. Use the official host and authenticated application route.</p>
        </div>
      </details>
      <HiringCalendar initialQuery={query} initialData={data} />
    </main>
  );
}
