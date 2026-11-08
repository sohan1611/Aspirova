import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import { Badge } from "@/components/ui/badge";
import CompanyFavicon from "@/components/CompanyFavicon";
import ListingFreshness from "@/components/ListingFreshness";
import RelativeDeadline from "@/components/RelativeDeadline";
import SaveButton from "@/components/SaveButton";
import {
  competitionMode,
  formatPrizePool,
  participantCount,
  teamSizeText,
} from "@/lib/competition";
import { formatCompensation } from "@/lib/compensation";
import { getCountry } from "@/lib/countries";
import {
  closedDeadlineLabel,
  hasExpiringDeadline,
  isCompetitionCategory,
} from "@/lib/deadline";
import { isSinglePlace, summarizeLocation } from "@/lib/location";
import { getSourceLabel } from "@/lib/sourceLabel";
import type { OpportunityListItem } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
  hackathon: "Hackathon",
  competition: "Competition",
  scholarship: "Scholarship",
};

const SOURCE_LABEL: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  amazon: "Amazon",
  unstop: "Unstop",
  remoteok: "RemoteOK",
  devpost: "Devpost",
};

const ABSOLUTE_DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function absoluteDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : ABSOLUTE_DATE_FORMATTER.format(date);
}

// Palettes and motifs live in globals.css (.comp-banner): the banner is one
// element painted with layered gradients, so it adds nothing to hydrate.
const BANNER_PALETTE_COUNT = 5;

export default function OpportunityCard({ item }: { item: OpportunityListItem }) {
  const companyName = item.company?.name ?? "Unknown company";
  const sourceLabel = item.source
    ? SOURCE_LABEL[item.source] ?? null
    : "apply_url" in item && typeof item.apply_url === "string"
      ? getSourceLabel(item.apply_url)
      : null;
  const { short: location, hiddenCount, full } = summarizeLocation(item.location);
  const countryFlag = isSinglePlace(item.location) ? getCountry(item.country)?.flag : null;
  const categoryLabel = item.category ? CATEGORY_LABEL[item.category] ?? item.category : null;
  const isCompetition = isCompetitionCategory(item.category);
  const hasPrize = isCompetition || item.category === "scholarship";
  const isInternship = item.category === "internship";
  const isRole = isInternship || item.category === "job";
  const payText = isRole ? formatCompensation(item.meta) : null;
  const prizeText = hasPrize ? formatPrizePool(item.meta) : null;
  const mode = hasPrize ? competitionMode(item) : null;
  const showCompetitionLocation = Boolean(location && location.trim().toLowerCase() !== mode?.toLowerCase());
  const registered = hasPrize ? participantCount(item.meta) : null;
  const teamSize = isCompetition ? teamSizeText(item.meta) : null;
  const offersPpi = hasPrize && item.meta?.offers_ppi === true;
  const offersPpo = hasPrize && item.meta?.offers_ppo === true;
  const duration = item.meta?.duration_months;
  const deadlineExpires = hasExpiringDeadline(item.category);
  const estimated = item.deadline_confidence !== "explicit";
  const openDeadlineLabel = isInternship ? "Apply by" : "Registers by";
  const closedDeadlineText = closedDeadlineLabel(item.category);
  const deadlineText = item.deadline
    ? deadlineExpires
      ? `${openDeadlineLabel} ${estimated ? "~" : ""}${absoluteDate(item.deadline)}`
      : `Closes ${estimated ? "~" : ""}${absoluteDate(item.deadline)}`
    : null;
  const slugHash = Array.from(item.slug).reduce(
    (hash, character) => (hash * 31 + character.charCodeAt(0)) >>> 0,
    0,
  );
  const paletteIndex = slugHash % BANNER_PALETTE_COUNT;
  const bannerMotif = item.category === "hackathon" ? "comp-banner--hatch" : "comp-banner--rings";
  const locationText = (
    <span className="min-w-0 break-words" title={full ?? undefined}>
      {countryFlag && <span aria-hidden="true">{countryFlag} </span>}
      {location}
      {hiddenCount > 0 && ` +${hiddenCount} more`}
    </span>
  );
  const freshness = (
    <ListingFreshness
      postedAt={item.posted_at}
      lastSeenAt={item.last_seen_at}
      absoluteText={absoluteDate(item.posted_at ?? item.last_seen_at)}
    />
  );
  const secondaryBadges = (
    <>
      {isRole && (item.meta?.part_time === true || item.meta?.timing === "part_time") && (
        <Badge variant="outline">Part-time</Badge>
      )}
      {isRole && typeof duration === "number" && Number.isInteger(duration) && duration >= 1 && duration <= 24 && (
        <Badge variant="outline">{duration} months</Badge>
      )}
      {isRole && item.meta?.job_offer === true && (
        <Badge variant="heritage">Job offer possible</Badge>
      )}
      {!isCompetition && mode && <Badge variant="outline">{mode}</Badge>}
      {!isCompetition && offersPpi && <Badge variant="heritage">Offers internship</Badge>}
      {!isCompetition && offersPpo && <Badge variant="heritage">Offers PPO</Badge>}
      {item.is_hidden && <Badge variant="heritage">Hidden gem</Badge>}
    </>
  );

  return (
    <div className="relative min-w-0 h-full">
      <HoverPrefetchLink
        href={`/opportunity/${item.slug}`}
        className="group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-soft transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {isCompetition && (
          <div className={`comp-banner ${bannerMotif} comp-banner--p${paletteIndex} relative h-24 shrink-0 overflow-hidden sm:h-28`}>
            {(item.closed_at || item.deadline) && (
              <RelativeDeadline
                deadline={item.deadline}
                closedAt={item.closed_at}
                category={item.category}
                absoluteText={deadlineText}
                closedText={closedDeadlineText}
                estimated={estimated}
                banner
              />
            )}
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col gap-3 p-4 sm:p-5">
          {isCompetition ? (
            <div className="flex min-h-11 min-w-0 flex-wrap items-center gap-2 pr-10 text-xs font-semibold text-muted-foreground sm:min-h-8">
              <CompanyFavicon company={item.company} size={24} />
              <span className="min-w-0 flex-1 break-words">{companyName}</span>
            </div>
          ) : (
            <div className="relative flex min-h-11 min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 pr-14">
              <div aria-hidden="true" className="absolute right-0 top-0 flex size-11 shrink-0 items-center justify-center">
                <CompanyFavicon company={item.company} size={44} />
              </div>
              {categoryLabel && (
                <Badge variant="secondary" className="font-semibold">{categoryLabel}</Badge>
              )}
              {(item.closed_at || deadlineText) && (
                <RelativeDeadline
                  deadline={item.deadline}
                  closedAt={item.closed_at}
                  category={item.category}
                  absoluteText={deadlineText}
                  closedText={closedDeadlineText}
                  estimated={estimated}
                />
              )}
              {freshness}
            </div>
          )}

          <h3 className="line-clamp-2 min-w-0 break-words font-serif text-[1.25rem] font-bold leading-tight text-card-foreground transition-colors group-hover:text-primary group-focus-visible:text-primary lg:text-[1.35rem]">
            {item.title}
          </h3>
          {item.summary && (
            <p className="line-clamp-2 break-words text-sm leading-5 text-muted-foreground">
              {item.summary}
            </p>
          )}

          {isCompetition ? (
            <>
              <div className="mt-auto grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 border-t border-border pt-3 text-xs text-muted-foreground [&>span]:flex [&>span]:min-w-0 [&>span]:items-start [&>span]:gap-1.5">
                {prizeText && (
                  <span className="text-accent-foreground">
                    <span aria-hidden="true" className="ico ico-trophy mt-0.5 size-3.5" />
                    <span className="break-words">
                      <span className="sr-only">Prize pool </span>{prizeText}
                    </span>
                  </span>
                )}
                {teamSize && (
                  <span><span aria-hidden="true" className="ico ico-users mt-0.5 size-3.5" /><span>{teamSize}</span></span>
                )}
                {(mode || location || countryFlag) && (
                  <span>
                    <span aria-hidden="true" className={`ico ${mode === "Online" ? "ico-globe" : "ico-map-pin"} mt-0.5 size-3.5`} />
                    <span>
                      {mode}{mode && (showCompetitionLocation || countryFlag) && " · "}
                      {showCompetitionLocation ? locationText : countryFlag && <span aria-hidden="true">{countryFlag}</span>}
                    </span>
                  </span>
                )}
                {item.is_remote && mode !== "Online" && <span><span aria-hidden="true" className="ico ico-globe mt-0.5 size-3.5" />Remote</span>}
                {deadlineText && (
                  <span><span aria-hidden="true" className="ico ico-calendar mt-0.5 size-3.5" /><span>{deadlineText}</span></span>
                )}
                {registered !== null && (
                  <span>
                    <span aria-hidden="true" className="ico ico-user-check mt-0.5 size-3.5" />
                    <span>{registered.toLocaleString("en-US")} registered</span>
                  </span>
                )}
                {offersPpi && (
                  <span><span aria-hidden="true" className="ico ico-user-check mt-0.5 size-3.5" />Offers internship</span>
                )}
                {offersPpo && (
                  <span><span aria-hidden="true" className="ico ico-user-check mt-0.5 size-3.5" />Offers PPO</span>
                )}
              </div>
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                {categoryLabel && <Badge variant="secondary">{categoryLabel}</Badge>}
                {freshness}
                {secondaryBadges}
              </div>
            </>
          ) : (
            <>
              <div className="mt-auto flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3 text-xs text-muted-foreground">
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  <span aria-hidden="true" className="ico ico-building size-3.5" />
                  <span className="min-w-0 break-words">{companyName}</span>
                </span>
                {(location || countryFlag) && (
                  <span className="inline-flex min-w-0 items-start gap-1.5">
                    <span aria-hidden="true" className="ico ico-map-pin size-3.5" />{locationText}
                  </span>
                )}
                {item.is_remote && (
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden="true" className="ico ico-globe size-3.5" />Remote
                  </span>
                )}
                {registered !== null && (
                  <span>{registered.toLocaleString("en-US")} registered</span>
                )}
              </div>
              <div className="flex min-h-11 min-w-0 flex-wrap items-center gap-1.5 pr-10 sm:min-h-8">
                {(payText || prizeText) && (
                  <span className="max-w-full break-words rounded-md bg-accent px-2 py-1 text-xs font-semibold text-accent-foreground">
                    <span className="sr-only">{payText ? "Pay " : "Prize pool "}</span>
                    {payText || prizeText}
                  </span>
                )}
                {secondaryBadges}
              </div>
            </>
          )}
          <div className={`flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs ${isCompetition ? "" : "pr-10"}`}>
            {sourceLabel && <span className="text-muted-foreground">via {sourceLabel}</span>}
            <span className="ml-auto font-medium text-primary">View →</span>
          </div>
        </div>
      </HoverPrefetchLink>
      <SaveButton
        slug={item.slug}
        title={item.title}
        className={isCompetition
          ? "absolute right-3 top-28 z-10 sm:top-[8.25rem]"
          : "absolute bottom-3 right-3 z-10"}
      />
    </div>
  );
}
