import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import SourceCompanyLogo from "@/components/SourceCompanyLogo";
import { Badge } from "@/components/ui/badge";
import type { ExternalCompany } from "@/lib/externalCompanies";

interface SourceCompanyCardProps {
  company: ExternalCompany;
}

export default function SourceCompanyCard({ company }: SourceCompanyCardProps) {
  return (
    <HoverPrefetchLink
      href={`/companies/${company.slug}`}
      className="group flex min-h-44 flex-col rounded-lg border border-border bg-card p-5 shadow-soft transition-colors duration-300 ease-premium hover:border-primary/45 focus-visible:border-primary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex items-start justify-between gap-3">
        <SourceCompanyLogo company={company} size={70} />
        <Badge variant="secondary">Straight to source</Badge>
      </div>

      <div className="mt-auto pt-6">
        <h2 className="min-w-0 break-words font-serif text-md font-bold leading-snug text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
          {company.name}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Official student roles + flagship programs
        </p>
      </div>
    </HoverPrefetchLink>
  );
}
