import type { AccountMe } from "@/lib/types";

export const PROFILE_COMPLETENESS_TOTAL = 3;

type ProfileCompletenessFields = Pick<
  AccountMe,
  "display_name" | "college" | "graduation_year"
>;

export function getProfileCompleteness({
  display_name,
  college,
  graduation_year,
}: ProfileCompletenessFields) {
  const completedFields = [
    Boolean(display_name?.trim()),
    Boolean(college?.trim()),
    graduation_year !== null,
  ].filter(Boolean).length;

  return {
    completedFields,
    percentage: (completedFields / PROFILE_COMPLETENESS_TOTAL) * 100,
  };
}
