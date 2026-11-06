import { ArrowUpRight, Building2, CalendarClock, Clock, ExternalLink, GraduationCap, ListChecks, MapPin, Trophy } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ApplyLink from "@/components/ApplyLink";
import AddToCalendar from "@/components/AddToCalendar";
import BookmarkButton from "@/components/BookmarkButton";
import CompanyFavicon from "@/components/CompanyFavicon";
import DeadlineBox from "@/components/DeadlineBox";
import RecordOpportunityView from "@/components/RecordOpportunityView";
import ReportIssueDialog from "@/components/ReportIssueDialog";
import ShareButton from "@/components/ShareButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import FollowCompanyButton from "@/components/FollowCompanyButton";
import SkillMatchCard from "@/components/SkillMatchCard";
import SimilarOpportunitiesList from "@/components/SimilarOpportunitiesList";
import { splitDescriptionSections } from "@/lib/descriptionSections";
import { getOpportunity, getSimilarOpportunities } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { describeApply, describeVerification } from "@/lib/applyDestination";
import {
  competitionMode,
  eligibilityText,
  eventDatesText,
  formatPrizePool,
  participantCount,
  prizeBreakdown,
  teamSizeText,
} from "@/lib/competition";
import {
  closedDeadlineLabel,
  estimatedClosedDeadlineLabel,
  hasExpiringDeadline,
  isDeadlinePast,
  isListingClosed,
} from "@/lib/deadline";
import {
  descriptionBlocksToHtml,
  parseDescriptionBlocks,
  type DescriptionBlock,
} from "@/lib/descriptionBlocks";
import { formatCompensation } from "@/lib/compensation";
import { summarizeLocation } from "@/lib/location";
import { getSourceLabel } from "@/lib/sourceLabel";
import type { OpportunityDetail, OpportunityListItem } from "@/lib/types";

// Sized so each path renders about four times a month; every regeneration is a full render and costs both Fluid CPU and an ISR write.
export const revalidate = 604800;

// Registers the route for on-demand ISR without prerendering any page at build
// time; without this Next leaves a dynamic segment fully per-request.
export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return [];
}

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
  hackathon: "Hackathon",
  competition: "Competition",
  scholarship: "Scholarship",
};
const SITE_URL = "https://www.aspirova.org";
// Organiser names can be long, and these labels include them: let them wrap on a phone.
const SOURCE_LINK_CLASSES = "h-auto min-h-11 max-w-full whitespace-normal py-2 text-center";

interface PageProps {
  params: Promise<{ slug: string }>;
}

function opportunityUrl(slug: string): string {
  return `${SITE_URL}/opportunity/${encodeURIComponent(slug)}`;
}

function nonEmpty(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

// Google requires complete JobPosting data for active jobs only, so omit the
// block unless every required field and a truthful country location are known.
function buildJobPostingJsonLd(
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
  const datePosted =
    nonEmpty(opportunity.posted_at) ?? nonEmpty(opportunity.first_seen_at);
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

// Apply labels end in a text arrow; this page draws an arrow icon instead.
function withoutArrow(label: string): string {
  return label.replace(/\s*→\s*$/, "");
}

function serializeJsonLd(value: Record<string, unknown>): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    return { title: "Opportunity not found" };
  }

  // The root layout's title template ("%s - Aspirova") appends the suffix -
  // do not repeat it here, or the <title> doubles up.
  const companyName = opportunity.company?.name ?? "";
  const title = `${opportunity.title}${companyName ? ` at ${companyName}` : ""}`;
  const description = opportunity.description_raw.slice(0, 160);
  const canonicalUrl = opportunityUrl(slug);

  return {
    title,
    description,
    alternates: { canonical: canonicalUrl },
    ...(opportunity.is_stale ? { robots: { index: false, follow: false } } : {}),
    // openGraph.title has no automatic template applied (unlike <title>),
    // so the "- Aspirova" suffix is added explicitly here for share
    // previews on Twitter/LinkedIn/etc.
    openGraph: {
      title: `${title} - Aspirova`,
      description,
      type: "website",
      url: canonicalUrl,
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function OpportunityPage({ params }: PageProps) {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    notFound();
  }

  const sourceLabel = getSourceLabel(opportunity.apply_url);
  const canonicalUrl = opportunityUrl(slug);
  const expires = hasExpiringDeadline(opportunity.category);
  const closedByDeadline =
    expires && !!opportunity.deadline && isDeadlinePast(opportunity.deadline);
  const closed = isListingClosed(
    opportunity.closed_at,
    opportunity.deadline,
    opportunity.category,
  );
  const descriptionBlocks = parseDescriptionBlocks(opportunity.description_raw);
  const sections = splitDescriptionSections(descriptionBlocks);
  const showSummary = Boolean(opportunity.summary?.trim()) && !sections.about.some(
    (block) => block.type === "paragraph" && block.text.trim() === opportunity.summary?.trim(),
  );
  const jobPostingJsonLd = buildJobPostingJsonLd(
    opportunity,
    canonicalUrl,
    closed,
    descriptionBlocks,
  );
  // is_stale is a separate, older-than-10-months signal from the backend and
  // can be true even when closed is false (no closed_at, no expiring
  // deadline) - a job with no deadline never trips `closed` on its own.
  const stale = opportunity.is_stale && !closed;
  const estimated =
    !opportunity.closed_at &&
    closedByDeadline &&
    opportunity.deadline_confidence !== "explicit";
  const closedStatusLabel = estimated
    ? estimatedClosedDeadlineLabel(opportunity.category)
    : closedDeadlineLabel(opportunity.category);
  const staleStatusLabel = estimatedClosedDeadlineLabel(opportunity.category);
  const apply = describeApply(opportunity.destination, opportunity.company?.name);
  const verification = describeVerification(opportunity.destination, opportunity.company?.name);
  const verifyLabel = verification.buttonLabel;
  const closedCaption = opportunity.closed_at
    ? `The source listing appears to be closed. ${verification.closedCaption}`
    : estimated
      ? `This estimated deadline may be wrong. ${verification.closedCaption}`
      : `This deadline has passed. ${verification.closedCaption}`;
  // Never invents a posted date: when posted_at is missing, this says only
  // when we first found the listing, not when it went up.
  const staleCaption = opportunity.posted_at
    ? `This was posted ${formatDate(opportunity.posted_at, "long")} — over 10 months ago — and Aspirova can't confirm it's still open. ${verification.statusCaption}`
    : `Aspirova first found this listing on ${formatDate(opportunity.first_seen_at, "long")}, over 10 months ago; its original posting date isn't available. We can't confirm it's still open. ${verification.statusCaption}`;
  const locationSummary = summarizeLocation(opportunity.location);
  const isRole = opportunity.category === "internship" || opportunity.category === "job";
  const payText = isRole ? formatCompensation(opportunity.meta) : null;
  const duration = opportunity.meta?.duration_months;
  const isCompetition = ["hackathon", "competition", "scholarship"].includes(opportunity.category ?? "");
  const prizes = prizeBreakdown(opportunity.meta);
  const registered = participantCount(opportunity.meta);
  const competitionDetails = isCompetition ? [
    ["Prize pool", formatPrizePool(opportunity.meta)],
    ["Prizes", prizes.length > 1 ? prizes.map(({ rank, amount }) => `${rank ? `${rank}: ` : ""}${amount}`).join(" · ") : null],
    ["Format", competitionMode(opportunity)],
    ["Team size", teamSizeText(opportunity.meta)],
    ["Registered", registered !== null ? registered.toLocaleString("en-US") : null],
    ["Open to", eligibilityText(opportunity.meta)],
    ["Entry", typeof opportunity.meta?.is_paid === "boolean" ? opportunity.meta.is_paid ? "Paid" : "Free" : null],
    ["Event dates", eventDatesText(opportunity.meta)],
  ].filter(([, value]) => value !== null) : [];
  let similarOpportunities: OpportunityListItem[] = [];

  try {
    similarOpportunities = await getSimilarOpportunities(slug);
  } catch {
    // Related opportunities are non-essential to the detail page.
  }

  return (
    <>
      {jobPostingJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: serializeJsonLd(jobPostingJsonLd) }}
        />
      )}
      <RecordOpportunityView
        slug={opportunity.slug}
        title={opportunity.title}
        companyName={opportunity.company?.name ?? null}
        companyDomain={opportunity.company?.domain ?? null}
        companyLogoUrl={opportunity.company?.logo_url ?? null}
        category={opportunity.category}
      />

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
        <Link href="/" className="inline-flex min-h-11 items-center text-sm text-muted-foreground underline-offset-4 hover:text-primary hover:underline">← All opportunities</Link>
        <div className="grid min-w-0 items-start gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0 [overflow-wrap:anywhere]">

            <header className="mt-4 sm:mt-6">
              <div className="flex flex-wrap items-start gap-3 sm:gap-4">
                <div className="flex size-12 shrink-0 items-center justify-center rounded-lg border border-border bg-card sm:size-14">
                  <CompanyFavicon company={opportunity.company} />
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <h1 className="break-words font-serif text-[1.875rem] font-bold leading-tight text-foreground sm:text-[2.25rem]">{opportunity.title}</h1>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                    <span className="inline-flex min-w-0 items-center gap-1.5">
                      <Building2 className="size-4 shrink-0" aria-hidden="true" />
                      {opportunity.company?.slug ? (
                        <Link href={`/companies/${opportunity.company.slug}`} className="inline-flex min-h-11 items-center break-words underline-offset-4 hover:text-primary hover:underline">
                          {opportunity.company.name}
                        </Link>
                      ) : opportunity.company?.name ?? "Independent listing"}
                    </span>
                    {locationSummary.short && <>
                      <span aria-hidden="true">·</span>
                      <span className="inline-flex min-w-0 items-center gap-1.5" title={locationSummary.full ?? undefined}>
                        <MapPin className="size-4 shrink-0" aria-hidden="true" /><span className="break-words">{locationSummary.short}</span>
                      </span>
                      {locationSummary.hiddenCount > 0 && <details className="max-w-full">
                        <summary className="min-h-11 cursor-pointer content-center">+{locationSummary.hiddenCount} more</summary>
                        <p className="mt-2 max-w-prose break-words leading-6">{locationSummary.full}</p>
                      </details>}
                    </>}
                  </div>
                </div>
                {sourceLabel && <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs font-medium">
                  <ExternalLink className="size-3" aria-hidden="true" />via {sourceLabel}
                </span>}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 sm:mt-4">
                {opportunity.category && (
                  <Badge variant="secondary" className="rounded-full text-xs px-2.5 py-1">
                    {CATEGORY_LABEL[opportunity.category] ?? opportunity.category}
                  </Badge>
                )}
                {opportunity.is_remote && (
                  <Badge variant="secondary" className="rounded-full text-xs px-2.5 py-1">
                    Remote
                  </Badge>
                )}
                {opportunity.is_hidden && (
                  <Badge variant="secondary" className="rounded-full px-2.5 py-1">
                    Hidden gem
                  </Badge>
                )}
                {isRole && (opportunity.meta?.part_time === true || opportunity.meta?.timing === "part_time") && (
                  <Badge variant="outline">Part-time</Badge>
                )}
                {isRole && typeof duration === "number" && Number.isInteger(duration) && duration >= 1 && duration <= 24 && (
                  <Badge variant="outline">{duration} months</Badge>
                )}
                {isRole && opportunity.meta?.job_offer === true && <Badge variant="secondary">Job offer possible</Badge>}
              </div>

              {payText && (
                <p className="mt-3 flex min-w-0 items-start gap-2 text-sm text-foreground/80">
                  <span className="eyebrow shrink-0 pt-0.5 text-primary">Pay</span>
                  <span className="min-w-0 break-words font-medium">{payText}</span>
                </p>
              )}

              {opportunity.posted_at && (
                <p className="mt-3 text-sm text-muted-foreground">
                  Posted {formatDate(opportunity.posted_at, "long")}
                </p>
              )}
            </header>
            {stale && (
              <div
                role="status"
                className="mt-8 max-w-3xl rounded-md border border-warning/25 bg-warning/15 px-4 py-3 text-sm leading-6 text-warning-foreground dark:text-warning"
              >
                <p className="font-medium">This listing is old and likely closed.</p>
                <p className="mt-1 text-xs leading-5 opacity-90">{staleCaption}</p>
              </div>
            )}

            <div className="border-b border-border pb-6">
              <section aria-label="Application actions" className="mt-5 min-w-0 [&_button]:min-h-11 [&_a]:min-h-11 sm:mt-6">
                <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
                  <div className="flex w-full min-w-0 max-w-full flex-wrap items-center gap-3 sm:contents">
                    {closed ? (
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-secondary px-4 py-2 text-sm font-medium text-muted-foreground">{closedStatusLabel}</span>
                        <Button size="lg" variant="outline" className={SOURCE_LINK_CLASSES} asChild>
                          <a href={opportunity.apply_url} target="_blank" rel="noopener noreferrer">{withoutArrow(verifyLabel)}<ArrowUpRight className="size-4 shrink-0" aria-hidden="true" /></a>
                        </Button>
                      </div>
                    ) : stale ? (
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-secondary px-4 py-2 text-sm font-medium text-muted-foreground">{staleStatusLabel}</span>
                        <ApplyLink slug={opportunity.slug} href={opportunity.apply_url} size="lg" variant="outline" className={SOURCE_LINK_CLASSES}>{withoutArrow(verifyLabel)}<ArrowUpRight className="size-4 shrink-0" aria-hidden="true" /></ApplyLink>
                      </div>
                    ) : (
                      <ApplyLink slug={opportunity.slug} href={opportunity.apply_url} size="lg" className={SOURCE_LINK_CLASSES}>{withoutArrow(apply.buttonLabel)}<ArrowUpRight className="size-4 shrink-0" aria-hidden="true" /></ApplyLink>
                    )}
                    <BookmarkButton slug={opportunity.slug} />
                  </div>
                  <ShareButton slug={opportunity.slug} title={opportunity.title} />
                  {opportunity.company?.slug && <div className="min-w-0 max-w-full [&>div]:mt-0 sm:ml-auto"><FollowCompanyButton slug={opportunity.company.slug} companyName={opportunity.company.name} /></div>}
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                  <p className="max-w-lg text-xs leading-5 text-muted-foreground">{closed ? closedCaption : stale ? verification.caption : apply.caption}</p>
                  <ReportIssueDialog opportunitySlug={opportunity.slug} />
                </div>
              </section>

              {opportunity.deadline && (
                <div className="mt-5 flex flex-wrap items-center gap-3 [&_button]:min-h-11">
                  <DeadlineBox deadlineIso={opportunity.deadline} closed={closed}>
                    <Clock className="size-4 shrink-0" aria-hidden="true" />
                    <span>
                      {closed ? `${closedStatusLabel}:` : "Deadline:"}{" "}
                      <span className="tnum">
                        {formatDate(opportunity.deadline, "numeric")}
                      </span>
                      {opportunity.deadline_confidence !== "explicit" ? " (estimated)" : ""}
                    </span>
                  </DeadlineBox>
                  {!closed && (
                    <AddToCalendar
                      event={{
                        slug: opportunity.slug,
                        title: opportunity.title,
                        deadline: opportunity.deadline,
                        url: canonicalUrl,
                        estimated: opportunity.deadline_confidence !== "explicit",
                      }}
                    />
                  )}
                </div>
              )}

            </div>
            {(showSummary || opportunity.reopen_estimate) && (
              <aside className="mt-6 rounded-lg border border-border bg-card p-4 sm:p-5">
                {showSummary && (
                  <div>
                    <p className="eyebrow">At a glance</p>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground sm:text-base">
                      {opportunity.summary}
                    </p>
                  </div>
                )}

                {opportunity.reopen_estimate && (
                  <div
                    className={
                      showSummary ? "mt-6 border-t border-border pt-6" : undefined
                    }
                  >
                    <div className="flex items-center gap-2">
                      <CalendarClock
                        className="size-4 shrink-0 text-primary"
                        aria-hidden="true"
                      />
                      <p className="eyebrow">Reopen outlook</p>
                    </div>
                    <p className="tnum mt-3 font-medium text-foreground">
                      Typically opens {opportunity.reopen_estimate.window}
                    </p>
                    <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                      {opportunity.reopen_estimate.note} This is an estimate based on{" "}
                      {opportunity.reopen_estimate.basis === "historical"
                        ? "past openings"
                        : "curated information"}
                      .
                    </p>
                  </div>
                )}
              </aside>
            )}

            <article className="mt-6 sm:mt-8" aria-labelledby="about-role-heading">
              <h2 id="about-role-heading" className="font-serif text-xl font-bold sm:text-2xl">About the role</h2>
              <div className="mt-4 space-y-4 text-sm leading-6 text-muted-foreground sm:text-[0.95rem] sm:leading-7">
                <DescriptionBlocks blocks={sections.about} />
              </div>
              {(sections.requirements.length > 0 || sections.eligibility.length > 0) && (
                <div className={`mt-6 grid gap-4 border-t border-border pt-6 sm:mt-8 sm:gap-6 sm:pt-8 ${sections.requirements.length > 0 && sections.eligibility.length > 0 ? "md:grid-cols-2" : ""}`}>
                  {sections.requirements.length > 0 && <section className="min-w-0 rounded-lg border border-border bg-card p-4 sm:p-5" aria-labelledby="requirements-heading">
                    <h3 id="requirements-heading" className="flex items-center gap-2 font-serif text-xl font-bold"><ListChecks className="size-5 shrink-0 text-primary" aria-hidden="true" />Requirements</h3>
                    <div className="mt-4 space-y-4 text-sm leading-6 text-muted-foreground"><DescriptionBlocks blocks={sections.requirements} inCard /></div>
                  </section>}
                  {sections.eligibility.length > 0 && <section className="min-w-0 rounded-lg border border-border bg-card p-4 sm:p-5" aria-labelledby="eligibility-heading">
                    <h3 id="eligibility-heading" className="flex items-center gap-2 font-serif text-xl font-bold"><GraduationCap className="size-5 shrink-0 text-primary" aria-hidden="true" />Eligibility</h3>
                    <div className="mt-4 space-y-4 text-sm leading-6 text-muted-foreground"><DescriptionBlocks blocks={sections.eligibility} inCard /></div>
                  </section>}
                </div>
              )}
            </article>
            {competitionDetails.length > 0 && (
              <section className="mt-10 rounded-lg border border-border bg-card p-6" aria-labelledby="competition-details-heading">
                <h2 id="competition-details-heading" className="flex items-center gap-2 font-serif text-2xl font-bold"><Trophy className="size-5 text-primary" aria-hidden="true" />Event details</h2>
                <dl className="mt-4 divide-y divide-border text-sm">
                  {competitionDetails.map(([label, value]) => (
                    <div key={label} className="grid min-w-0 gap-1 py-3 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4">
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="min-w-0 break-words [overflow-wrap:anywhere]">{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            {opportunity.skills.length > 0 && (
              <section className="mt-10 border-t border-border pt-8" aria-labelledby="opportunity-skills-heading">
                <h2 id="opportunity-skills-heading" className="font-serif text-2xl font-bold">
                  Skills for this role
                </h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Skills we detected for this role.
                </p>
                <ul className="mt-4 flex flex-wrap gap-2" aria-label="Detected skills for this role">
                  {opportunity.skills.map((skill) => (
                    <li key={skill} className="max-w-full">
                      <Badge
                        variant="secondary"
                        className="max-w-full whitespace-normal break-words rounded-md bg-secondary px-3 py-1.5 text-sm normal-case tracking-normal"
                      >
                        {skill}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </section>
            )}

          </div>
          <aside className="min-w-0 space-y-4 lg:space-y-6 lg:pt-6" aria-label="Skills and similar opportunities">
            <SkillMatchCard skills={opportunity.skills} />
            <SimilarOpportunitiesList items={similarOpportunities} />
          </aside>
        </div>
      </main>
    </>
  );
}

function DescriptionBlocks({ blocks, inCard = false }: { blocks: DescriptionBlock[]; inCard?: boolean }) {
  return blocks.map((block, index) => {
    if (block.type === "heading") {
      const normalized = block.text.toLowerCase().replace(/[^a-z]/g, "");
      if (inCard && ["requirement", "requirements", "eligibility", "eligibilitycriteria"].includes(normalized)) return null;
      return inCard ? (
        <h4 key={index} className="font-serif text-base font-bold text-foreground">{block.text}</h4>
      ) : (
        <h3 key={index} className="pt-2 font-serif text-lg font-bold text-foreground first:pt-0">{block.text}</h3>
      );
    }
    if (block.type === "list") {
      return <ul key={index} className="list-disc space-y-2 pl-5">{block.items.map((item, itemIndex) => <li key={itemIndex} className="pl-1">{item}</li>)}</ul>;
    }
    return <p key={index} className="whitespace-pre-line">{block.text}</p>;
  });
}
