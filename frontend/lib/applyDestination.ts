import type { ApplyDestination, DestinationFacts } from "@/lib/types";

type Destination = ApplyDestination | null | undefined;

const APPLICATION_NOTE = "Aspirova never handles your application.";

export function destinationFacts(value?: unknown): DestinationFacts | null {
  if (!value || typeof value !== "object") return null;
  const facts = value as DestinationFacts;
  return Number.isInteger(facts.v) && facts.v >= 1 && typeof facts.valid === "boolean"
    && (typeof facts.host === "string" || facts.host === null)
    && typeof facts.employer_verified === "boolean" && Array.isArray(facts.warnings)
    && facts.warnings.every(warning => typeof warning === "string")
    ? facts : null;
}

export function destinationLines(facts: DestinationFacts | null): string[] {
  if (!facts) return [];
  if (!facts.valid) return ["Original link unavailable"];
  const lines = facts.host ? [`Applies on ${facts.host}`] : [];
  if (facts.aggregator_warning) lines.push(facts.type === "aggregator"
    ? `Listed via ${facts.via || "an aggregator"} — not the employer's own page`
    : `Listed via ${facts.via || "a re-poster"}`);
  if (facts.status === "sign_in_required") lines.push("Sign-in required at the destination");
  if (facts.terminal_host && facts.terminal_host !== facts.host) lines.push(`Redirect target: ${facts.terminal_host}`);
  if (facts.warnings.includes("parked")) lines.push("Destination may be parked or for sale");
  else if (facts.warnings.some(warning => warning.startsWith("redirect_") || warning === "invalid_redirect")) lines.push("Redirect could not be verified");
  if (facts.status === "gone") lines.push("Destination returned a missing-page response at its last check");
  return lines;
}

function destinationCopy(destination: Destination, companyName?: string | null, facts?: DestinationFacts | null) {
  const name = companyName?.trim();
  const co = name || "the company";
  if (facts) {
    const host = facts.host || "the source";
    const verified = facts.employer_verified === true;
    return {
      buttonLabel: facts.aggregator_warning && facts.type === "aggregator"
        ? `Apply via ${facts.via || host} →` : "Apply at the source →",
      listing: verified ? `${co}'s verified careers destination (${host})` : `the listing on ${host}`,
      caveat: verified ? "" : "Employer origin has not been verified. ",
    };
  }
  if (!destination?.host) {
    return { buttonLabel: "Apply at the source →", listing: "the original listing", caveat: "" };
  }
  const { kind, host, label } = destination;
  switch (kind) {
    case "company":
      return {
        buttonLabel: "Apply at the source →",
        listing: `the listing on ${host}`,
        caveat: "Employer origin has not been verified. ",
      };
    case "ats":
      return {
        buttonLabel: "Apply at the source →",
        listing: `the listing hosted on ${label} (${host})`,
        caveat: "Employer origin has not been verified. ",
      };
    case "job_board":
      return {
        buttonLabel: `Apply via ${label} →`,
        listing: `this listing on ${label} (${host})`,
        caveat: `${label} is a job board, not ${co}'s own site. `,
      };
    case "event_platform":
      return {
        buttonLabel: `Apply on ${label} →`,
        listing: `this listing on ${label} (${host})`,
        caveat: label === "Unstop" ? "Unstop is an aggregator, not the employer's own page. " : "",
      };
    default:
      return {
        buttonLabel: "Apply at the source →",
        listing: `the original listing on ${host}`,
        caveat: `We haven't confirmed this is ${co}'s own site. `,
      };
  }
}

export function describeApply(destination: Destination, companyName?: string | null, facts?: DestinationFacts | null) {
  const { buttonLabel, listing, caveat } = destinationCopy(destination, companyName, facts);
  return { buttonLabel, caption: `Opens ${listing}. ${caveat}${APPLICATION_NOTE}` };
}

export function describeVerification(destination: Destination, companyName?: string | null, facts?: DestinationFacts | null) {
  const { buttonLabel, listing, caveat } = destinationCopy(destination, companyName, facts);
  return {
    buttonLabel: buttonLabel.replace(/^Apply /, "Verify "),
    caption: `Opens ${listing} so you can check whether it is still open. ${caveat}${APPLICATION_NOTE}`,
    statusCaption: `Open ${listing} to check its current status. ${caveat}`.trim(),
    closedCaption: `Open ${listing} to confirm — the source may still be accepting entries. ${caveat}`.trim(),
  };
}
