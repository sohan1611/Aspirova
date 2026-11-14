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

export type ProfileStrengthStep = {
  key: "display_name" | "college" | "graduation_year" | "field" | "skills" | "resume";
  label: string;
  reason: string;
  done: boolean;
  optional: boolean;
};

export function getProfileStrength(account: AccountMe, hasFieldSelections: boolean): {
  steps: ProfileStrengthStep[];
  done: number;
  total: number;
  percentage: number;
  nextStep: ProfileStrengthStep | null;
} {
  const steps: ProfileStrengthStep[] = [
    { key: "display_name", label: "Display name", reason: "Makes your account and emails feel personal.", done: Boolean(account.display_name?.trim()), optional: false },
    { key: "college", label: "College", reason: "Helps surface opportunities for your campus.", done: Boolean(account.college?.trim()), optional: false },
    { key: "graduation_year", label: "Graduation year", reason: "Finds programmes and roles for your stage.", done: account.graduation_year != null, optional: false },
    ...getProfileChecklist(account, hasFieldSelections).map((step) => ({
      ...step,
      key: step.key as "field" | "skills" | "resume",
    })),
  ];
  const done = steps.filter((step) => step.done).length;
  const total = steps.length;
  return {
    steps,
    done,
    total,
    percentage: (done / total) * 100,
    nextStep: steps.find((step) => !step.done && !step.optional)
      ?? steps.find((step) => !step.done) ?? null,
  };
}
