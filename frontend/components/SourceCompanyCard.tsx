import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import { Badge } from "@/components/ui/badge";
import type { ExternalCompany } from "@/lib/externalCompanies";

interface SourceCompanyCardProps {
  company: ExternalCompany;
}

export default function SourceCompanyCard({ company }: SourceCompanyCardProps) {
  return (
    <Link
      href={`/companies/${company.slug}`}
      className="group flex min-h-44 flex-col rounded-xl border border-border bg-card p-5 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-1 hover:border-primary/45 hover:[box-shadow:var(--shadow-md)] focus-visible:-translate-y-1 focus-visible:border-primary/45 focus-visible:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="w-fit rounded-xl border border-border bg-secondary/40 p-1.5 shadow-soft">
          <CompanyFavicon
            company={{
              slug: company.slug,
              name: company.name,
              domain: company.domain,
              logo_url: null,
            }}
            size={56}
          />
        </div>
        <Badge variant="heritage">Straight to source</Badge>
      </div>

      <div className="mt-auto pt-6">
        <h2 className="min-w-0 break-words font-sans text-md font-medium leading-snug text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
          {company.name}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Official student roles + flagship programs
        </p>
      </div>
    </Link>
  );
}
