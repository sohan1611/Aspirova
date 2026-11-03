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
    graduation_year != null,
  ].filter(Boolean).length;

  return {
    completedFields,
    percentage: (completedFields / PROFILE_COMPLETENESS_TOTAL) * 100,
  };
}

export function getProfileChecklist(account: AccountMe, hasFieldSelections: boolean) {
  return [
    {
      key: "field",
      label: "Field and interests",
      reason: "Shapes your For You feed.",
      done: hasFieldSelections,
      optional: false,
    },
    {
      key: "skills",
      label: "Skills",
      reason: "Lets us show which listings fit what you know.",
      done: Boolean(account.skills?.length),
      optional: false,
    },
    {
      key: "resume",
      label: "Resume",
      reason: "Checks formatting and content signals, not your odds of being hired.",
      done: Boolean(account.resume),
      optional: true,
    },
  ];
}
