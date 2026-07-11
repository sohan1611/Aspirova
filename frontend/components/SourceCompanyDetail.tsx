import { ExternalLink } from "lucide-react";
import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ExternalCompany } from "@/lib/externalCompanies";

interface SourceCompanyDetailProps {
  company: ExternalCompany;
}

export default function SourceCompanyDetail({ company }: SourceCompanyDetailProps) {
  return (
    <>
      <Link
        href="/companies"
        className="inline-flex text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
      >
        ← All companies
      </Link>

      <header className="mt-8 border-b border-border pb-10">
        <div className="flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:gap-7">
          <div className="rounded-xl border border-border bg-card p-2 shadow-soft">
            <CompanyFavicon
              company={{
                slug: company.slug,
                name: company.name,
                domain: company.domain,
                logo_url: null,
              }}
              size={72}
            />
          </div>

          <div className="min-w-0">
            <p className="eyebrow">Straight to source</p>
            <h1 className="mt-2 break-words font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
              {company.name}
            </h1>
          </div>
        </div>

        <p className="mt-6 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {company.note}
        </p>

        <Button asChild className="mt-6">
          <a
            href={company.careersUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {company.careersLabel}
            <ExternalLink aria-hidden="true" />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </Button>
      </header>

      <section className="mt-10" aria-labelledby="flagship-programs-title">
        <p className="eyebrow">The annual calendar</p>
        <h2
          id="flagship-programs-title"
          className="mt-2 font-serif text-2xl font-semibold leading-tight text-foreground sm:text-3xl"
        >
          Flagship annual programs
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          Timelines are tentative, based on recent years — always confirm on the official page.
        </p>

        <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2">
          {company.programs.map((program) => (
            <article
              key={program.name}
              className="rounded-xl border border-border bg-card p-5 shadow-soft"
            >
              <h3 className="font-medium text-card-foreground">{program.name}</h3>
              <Badge
                variant={program.scope === "India" ? "heritage" : "secondary"}
                className="mt-3"
              >
                {program.scope === "India" ? "🇮🇳" : "🌍"} {program.scope}
              </Badge>
              <p className="tnum mt-4 text-sm leading-6 text-muted-foreground">
                {program.timeline}
              </p>
              <a
                href={program.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 transition-colors hover:text-primary/80 hover:underline"
              >
                Official page
                <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </article>
          ))}
        </div>

        <p className="mt-8 text-sm leading-6 text-muted-foreground">
          Aspirova always links you to the original source — every application happens on the
          official site.
        </p>
      </section>
    </>
  );
}
