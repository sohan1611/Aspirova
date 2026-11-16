export const UNCONFIRMED_ELIGIBILITY = "Eligibility not confirmed — check the official page";

export function programmeEligibility(value: string | null | undefined): string {
  return value?.trim() || UNCONFIRMED_ELIGIBILITY;
}
