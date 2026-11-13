"use client";

import { Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export default function CalendarHeader() {
  return (
    <header>
      <h1 className="font-serif text-3xl font-bold tracking-tight sm:text-4xl">Hiring Calendar</h1>
      <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
        Key registration dates for internships, hackathons, fellowships, research programmes,
        government exams and company hiring drives. Official dates where published, past-year patterns otherwise.
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span><span className="text-primary" aria-hidden="true">●</span> Official</span>
        <span><span aria-hidden="true">◌</span> Tentative</span>
        <span className="font-medium text-success"><span aria-hidden="true">●</span> Open now</span>
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" className="min-h-11 px-2 text-xs text-muted-foreground"><Info aria-hidden="true" />How dates work</Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="max-h-[75dvh] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto text-sm leading-6" aria-label="How calendar dates work">
            <h2 className="font-semibold">How dates work</h2>
            <p className="mt-2 text-muted-foreground">
              Plan around application openings. A 2027 programme may accept applications in 2026,
              and a 2027 drive may recruit for 2028. The cycle year follows the programme intake.
              All projected months are tentative historical trends unless labelled official.
              A historical watch item becomes open only after an official call is verified.
            </p>
            <h3 className="mt-4 font-semibold">Before you apply</h3>
            <div className="mt-2 space-y-3 text-muted-foreground">
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
          </PopoverContent>
        </Popover>
      </div>
    </header>
  );
}
