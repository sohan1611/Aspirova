import { descriptionBlocksToHtml, type DescriptionBlock } from "./descriptionBlocks";
import type { OpportunityDetail } from "./types";

function nonEmpty(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

// Google requires complete JobPosting data for active jobs only, so omit the
// block unless every required field and a truthful country location are known.
export function buildJobPostingJsonLd(
  opportunity: OpportunityDetail,
  canonicalUrl: string,
  closed: boolean,
  descriptionBlocks: DescriptionBlock[],
): Record<string, unknown> | null {
  if (
    (opportunity.category !== "job" && opportunity.category !== "internship") ||
    closed ||
    opportunity.is_stale ||
    opportunity.is_hidden ||
    opportunity.is_remote === null
  ) {
    return null;
  }

  const title = nonEmpty(opportunity.title);
  const description = descriptionBlocksToHtml(descriptionBlocks);
  const companyName = nonEmpty(opportunity.company?.name);
  const datePosted = nonEmpty(opportunity.posted_at);
  const country = nonEmpty(opportunity.country);

  if (!title || !description || !companyName || !datePosted || !country) {
    return null;
  }

  const hiringOrganization: Record<string, string> = {
    "@type": "Organization",
    name: companyName,
  };
  const companyDomain = nonEmpty(opportunity.company?.domain);
  if (companyDomain) {
    hiringOrganization.sameAs = `https://${companyDomain}`;
  }
  const companyLogoUrl = nonEmpty(opportunity.company?.logo_url);
  if (companyLogoUrl) {
    hiringOrganization.logo = companyLogoUrl;
  }

  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title,
    description,
    datePosted,
    hiringOrganization,
    directApply: false,
    url: canonicalUrl,
  };

  if (opportunity.category === "internship") {
    jsonLd.employmentType = "INTERN";
  }

  if (opportunity.deadline && opportunity.deadline_confidence === "explicit") {
    jsonLd.validThrough = opportunity.deadline;
  }

  const location = nonEmpty(opportunity.location);
  if (opportunity.is_remote) {
    jsonLd.jobLocationType = "TELECOMMUTE";
    jsonLd.applicantLocationRequirements = {
      "@type": "Country",
      name: country,
    };
  } else {
    jsonLd.jobLocation = {
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressCountry: country,
        ...(location ? { addressLocality: location } : {}),
      },
    };
  }

  return jsonLd;
}
