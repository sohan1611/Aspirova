import { describeApply, describeVerification, destinationFacts } from "./applyDestination";
import { closedDeadlineLabel, estimatedClosedDeadlineLabel, isListingClosed } from "./deadline";
import { safeExternalUrl } from "./safeUrl";
import type { BookmarkStage, SavedOpportunityItem } from "./types";

export const BOOKMARK_STAGES = [
  { value: "saved", label: "Saved" },
  { value: "planned", label: "Planned" },
  { value: "applied", label: "Applied" },
  { value: "assessment", label: "Assessment" },
  { value: "interviewing", label: "Interview" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
  { value: "archived", label: "Archived" },
] as const satisfies readonly { value: BookmarkStage; label: string }[];

export function stageLabel(stage: BookmarkStage): string {
  return BOOKMARK_STAGES.find(option => option.value === stage)?.label ?? stage;
}

export function isInProgress(stage: BookmarkStage): boolean {
  return ["planned", "applied", "assessment", "interviewing"].includes(stage);
}

// An explicit application confirmation must not move a later stage backwards.
export function isAppliedStage(stage: BookmarkStage | undefined): boolean {
  return stage !== undefined && ["applied", "assessment", "interviewing", "offer", "rejected"].includes(stage);
}

export function bookmarkCounts(items: readonly Pick<SavedOpportunityItem, "bookmark_status">[]) {
  const stages: Record<BookmarkStage, number> = {
    saved: 0, planned: 0, applied: 0, assessment: 0, interviewing: 0, offer: 0, rejected: 0, archived: 0,
  };
  for (const item of items) stages[item.bookmark_status] += 1;
  return {
    stages,
    tracked: items.length - stages.archived,
    inProgress: items.filter(item => isInProgress(item.bookmark_status)).length,
  };
}

export function relevantDate(item: SavedOpportunityItem): string | null {
  return (["interviewing", "assessment"].includes(item.bookmark_status) ? item.status_date : null)
    || item.deadline;
}

function dateOrder(value: string | null): number {
  const timestamp = value ? Date.parse(value) : NaN;
  return Number.isNaN(timestamp) ? Infinity : timestamp;
}

export function nextUpItems(items: readonly SavedOpportunityItem[]): SavedOpportunityItem[] {
  return items.filter(item => isInProgress(item.bookmark_status)).sort((a, b) => {
    const first = dateOrder(relevantDate(a));
    const second = dateOrder(relevantDate(b));
    return first === second ? a.slug.localeCompare(b.slug) : first < second ? -1 : 1;
  });
}

const DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", timeZone: "UTC",
});

export function actionDateLabel(item: SavedOpportunityItem): string | null {
  const value = item.status_date || item.deadline;
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  const label = item.status_date ? `${stageLabel(item.bookmark_status)} on` : "Listing deadline";
  const estimated = !item.status_date && item.deadline_confidence !== "explicit";
  return `${label} ${estimated ? "~" : ""}${DATE_FORMATTER.format(new Date(value))}`;
}

export function actionSource(item: SavedOpportunityItem) {
  // Match the #206 safety gate even if a flagged row's status is inconsistent.
  if (item.status === "withdrawn" || item.safety || item.meta?.safety) {
    return {
      kind: "withdrawn" as const,
      href: null,
      warning: item.safety?.kind === "scam" ? "Warning: reported as a scam" : "This listing was withdrawn",
      buttonLabel: "Listing withdrawn",
      caption: "Do not pay any fee or share bank or ID documents.",
    };
  }
  const closed = item.status === "closed" || item.status === "expired"
    || isListingClosed(item.closed_at, item.deadline, item.category);
  const copy = closed
    ? describeVerification(item.destination, item.company?.name, destinationFacts(item.destination_facts))
    : describeApply(item.destination, item.company?.name, destinationFacts(item.destination_facts));
  const estimated = !item.closed_at && item.status !== "closed" && item.status !== "expired"
    && item.deadline_confidence !== "explicit";
  return {
    kind: closed ? "closed" as const : "open" as const,
    href: safeExternalUrl(item.apply_url),
    warning: closed
      ? estimated ? estimatedClosedDeadlineLabel(item.category) : closedDeadlineLabel(item.category)
      : null,
    ...copy,
  };
}
