import type { ApplyDestination } from "@/lib/types";

type Destination = ApplyDestination | null | undefined;

const APPLICATION_NOTE = "Aspirova never handles your application.";

function destinationCopy(destination: Destination, companyName?: string | null) {
  const name = companyName?.trim();
  const co = name || "the company";
  if (!destination?.host) {
    return { buttonLabel: "Apply at the source →", listing: "the original listing", caveat: "" };
  }
  const { kind, host, label } = destination;
  switch (kind) {
    case "company":
      return {
        buttonLabel: name ? `Apply on ${co} →` : "Apply at the source →",
        listing: `${co}'s own site (${host})`,
        caveat: "",
      };
    case "ats":
      return {
        buttonLabel: name ? `Apply on ${co} →` : "Apply at the source →",
        listing: `${co}'s careers listing, hosted on ${label} (${host})`,
        caveat: "",
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
        caveat: "",
      };
    default:
      return {
        buttonLabel: "Apply at the source →",
        listing: `the original listing on ${host}`,
        caveat: `We haven't confirmed this is ${co}'s own site. `,
      };
  }
}

export function describeApply(destination: Destination, companyName?: string | null) {
  const { buttonLabel, listing, caveat } = destinationCopy(destination, companyName);
  return { buttonLabel, caption: `Opens ${listing}. ${caveat}${APPLICATION_NOTE}` };
}

export function describeVerification(destination: Destination, companyName?: string | null) {
  const { buttonLabel, listing, caveat } = destinationCopy(destination, companyName);
  return {
    buttonLabel: buttonLabel.replace(/^Apply /, "Verify "),
    caption: `Opens ${listing} so you can check whether it is still open. ${caveat}${APPLICATION_NOTE}`,
    statusCaption: `Open ${listing} to check its current status. ${caveat}`.trim(),
    closedCaption: `Open ${listing} to confirm — the source may still be accepting entries. ${caveat}`.trim(),
  };
}
