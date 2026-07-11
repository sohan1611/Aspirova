import { ExternalLink } from "lucide-react";
import CompanyFavicon from "@/components/CompanyFavicon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ResearchProgram } from "@/lib/researchPrograms";

interface ResearchProgramCardProps {
  program: ResearchProgram;
}

export default function ResearchProgramCard({ program }: ResearchProgramCardProps) {
  return (
    <article className="flex h-full flex-col rounded-xl border border-border bg-card p-5 shadow-soft">
      <div className="flex items-start justify-between gap-3">
        <div className="w-fit rounded-xl border border-border bg-secondary/40 p-1.5 shadow-soft">
          <CompanyFavicon
            company={{
              slug: program.slug,
              name: program.host,
              domain: program.domain,
              logo_url: null,
            }}
            size={44}
          />
        </div>
        <Badge variant={program.scope === "National" ? "heritage" : "secondary"}>
          {program.scope}
        </Badge>
      </div>

      <div className="mt-5">
        <h2 className="font-serif text-xl font-semibold leading-snug text-card-foreground">
          {program.name}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {program.host} · {program.location}
        </p>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">{program.blurb}</p>
      </div>

      <div className="mt-5 space-y-2 text-sm leading-6 text-muted-foreground">
        <p>Eligibility: {program.eligibility}</p>
        <p className="tnum">When: {program.timeline}</p>
        {program.stipend && <p>Stipend: {program.stipend}</p>}
      </div>

      <div className="mt-auto pt-6">
        <Button asChild variant="outline" size="sm">
          <a href={program.applyUrl} target="_blank" rel="noopener noreferrer">
            Apply on the official site
            <ExternalLink aria-hidden="true" />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </Button>
      </div>
    </article>
  );
}
