import { programmeEligibility, UNCONFIRMED_ELIGIBILITY } from "@/lib/programmeEligibility";
import { safeExternalUrl } from "@/lib/safeUrl";

export default function ProgrammeEligibility({ value, officialUrl }: {
  value: string | null | undefined; officialUrl: string | null | undefined;
}) {
  const text = programmeEligibility(value);
  const href = safeExternalUrl(officialUrl);
  return text === UNCONFIRMED_ELIGIBILITY && href
    ? <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{text}<span className="sr-only"> (opens in a new tab)</span></a>
    : <span>{text}</span>;
}
