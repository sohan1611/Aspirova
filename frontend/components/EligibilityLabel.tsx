"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { eligibilityEvidenceText, eligibilityLabelText, remoteLabelText, parseEligibilityParams, type EligibilityParams } from "@/lib/eligibility";
import type { EligibilityFacts } from "@/lib/types";

function Label({ facts, filters = {} }: { facts?: EligibilityFacts | null; filters?: EligibilityParams }) {
  const text = eligibilityLabelText(facts, filters);
  if (!text) return null;
  const evidence = text === "Eligibility not stated"
    ? "The listing does not state the selected eligibility dimension. Check the listing before applying."
    : eligibilityEvidenceText(facts);
  return <span className="relative block min-w-0 max-w-full truncate text-xs text-muted-foreground" title={evidence}>
    {text}<span className="sr-only">. {evidence}</span>
  </span>;
}

function FilteredLabel({ facts }: { facts?: EligibilityFacts | null }) {
  const params = useSearchParams();
  return <Label facts={facts} filters={parseEligibilityParams(params)} />;
}

export default function EligibilityLabel({ facts }: { facts?: EligibilityFacts | null }) {
  return <Suspense fallback={<Label facts={facts} />}><FilteredLabel facts={facts} /></Suspense>;
}


function RemoteLine({ facts, isRemote, scopeActive = false }: { facts?: EligibilityFacts | null; isRemote: boolean; scopeActive?: boolean }) {
  const text = remoteLabelText(facts, isRemote, scopeActive);
  if (!text) return null;
  const evidence = eligibilityEvidenceText(facts) || "The source marks this role remote; where you can work from is not stated. Check the listing.";
  return <span className="relative block min-w-0 max-w-full truncate text-xs text-muted-foreground" title={evidence}>
    {text}<span className="sr-only">. {evidence}</span>
  </span>;
}
function FilteredRemoteLine({ facts, isRemote }: { facts?: EligibilityFacts | null; isRemote: boolean }) {
  const params = useSearchParams();
  return <RemoteLine facts={facts} isRemote={isRemote} scopeActive={["domestic", "abroad"].includes(params.get("scope") ?? "")} />;
}
export function RemoteLabel({ facts, isRemote }: { facts?: EligibilityFacts | null; isRemote: boolean }) {
  return <Suspense fallback={<RemoteLine facts={facts} isRemote={isRemote} />}><FilteredRemoteLine facts={facts} isRemote={isRemote} /></Suspense>;
}
