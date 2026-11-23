import { ELIGIBILITY_DIMENSIONS, eligibilityValueText } from "@/lib/eligibility";
import type { EligibilityFacts } from "@/lib/types";

export default function EligibilitySection({ facts }: { facts?: EligibilityFacts | null }) {
  return <section className="space-y-4 rounded-lg border border-border bg-card p-5" aria-labelledby="eligibility-facts-heading">
    <h2 id="eligibility-facts-heading" className="font-serif text-xl font-bold">Eligibility</h2>
    <p className="text-sm text-muted-foreground">Stated requirements only — check all requirements in the source listing.</p>
    <dl className="space-y-3 text-sm">
      {ELIGIBILITY_DIMENSIONS.map(([key, label]) => {
        const fact = facts?.[key];
        return <div key={key}>
          <dt className="font-semibold">{label}</dt>
          <dd className="break-words text-muted-foreground">{fact ? <>
            {eligibilityValueText(key, fact)} — check all requirements
            <blockquote className="mt-1 border-l-2 border-border pl-3">“{fact.evidence}” <span className="text-xs">({fact.source})</span></blockquote>
          </> : "Not stated — check the listing"}</dd>
        </div>;
      })}
    </dl>
  </section>;
}
