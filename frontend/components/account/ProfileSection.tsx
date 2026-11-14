"use client";

import type { User } from "@supabase/supabase-js";
import { Check, ChevronDown, Compass, Gauge, GraduationCap, Loader2, Lock, Pencil, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { EmptyState, Meter, SectionHeader, SettingsCard, SettingsRow } from "@/components/account/primitives";
import { CollegePicker } from "@/components/CollegePicker";
import { CountryPicker } from "@/components/CountryPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { updateAccount } from "@/lib/api";
import { storeCountryCode, useStoredCountryCode } from "@/lib/country";
import { getCountry } from "@/lib/countries";
import { hasFieldProfileSelections, requestOnboarding, useFieldProfile } from "@/lib/fieldProfile";
import { getProfileStrength } from "@/lib/profileCompleteness";
import { getDivision, getStream, interestsFor } from "@/lib/taxonomy";
import type { AccountMe } from "@/lib/types";
import { useHydrated } from "@/lib/useHydrated";
import { cn } from "@/lib/utils";

interface ProfileSectionProps {
  account: AccountMe;
  accessToken: string;
  user: User;
  onAccountChange: (account: AccountMe) => void;
}

function getProfilePatch(
  account: AccountMe,
  displayName: string,
  college: string,
  graduationYear: string,
): Partial<Pick<AccountMe, "display_name" | "college" | "graduation_year">> {
  const normalizedName = displayName.trim() || null;
  const normalizedCollege = college.trim() || null;
  const normalizedYear = graduationYear ? Number(graduationYear) : null;
  const patch: Partial<
    Pick<AccountMe, "display_name" | "college" | "graduation_year">
  > = {};

  if (normalizedName !== account.display_name) patch.display_name = normalizedName;
  if (normalizedCollege !== account.college) patch.college = normalizedCollege;
  if (normalizedYear !== account.graduation_year) patch.graduation_year = normalizedYear;

  return patch;
}

type ProfileDraft = { displayName: string; college: string; graduationYear: string };

function readProfileDraft(userId: string): ProfileDraft | null {
  try {
    const raw = sessionStorage.getItem(`aspirova:profile-draft:${userId}`);
    if (!raw) return null;
    const draft: unknown = JSON.parse(raw);
    if (!draft || typeof draft !== "object") return null;
    const value = draft as Partial<ProfileDraft>;
    if (typeof value.displayName !== "string" || typeof value.college !== "string" ||
      typeof value.graduationYear !== "string") return null;
    return value as ProfileDraft;
  } catch {
    return null;
  }
}

export default function ProfileSection({
  account,
  accessToken,
  user,
  onAccountChange,
}: ProfileSectionProps) {
  const [displayName, setDisplayName] = useState(
    () => readProfileDraft(user.id)?.displayName ?? account.display_name ?? "",
  );
  const [college, setCollege] = useState(
    () => readProfileDraft(user.id)?.college ?? account.college ?? "",
  );
  const [collegeEntryMode, setCollegeEntryMode] = useState<"list" | "manual">("list");
  const [graduationYear, setGraduationYear] = useState(
    () => readProfileDraft(user.id)?.graduationYear ?? account.graduation_year?.toString() ?? "",
  );
  const [collegeCountryNotice, setCollegeCountryNotice] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const storedCountryCode = useStoredCountryCode();
  const hydrated = useHydrated();
  const selectedCountry = hydrated ? getCountry(storedCountryCode) : undefined;
  const { profile: fieldProfile, hydrated: fieldProfileHydrated } = useFieldProfile();
  const fieldStream = getStream(fieldProfile.stream);
  const fieldDivisionLabels = fieldProfile.divisions
    .map((divisionKey) => getDivision(fieldProfile.stream, divisionKey)?.label)
    .filter((label): label is string => Boolean(label));
  const fieldInterestLabels = interestsFor(fieldProfile.stream, fieldProfile.divisions)
    .filter((interest) => fieldProfile.interests.includes(interest.key))
    .map((interest) => interest.label);
  const currentYear = new Date().getFullYear();
  const graduationYears = Array.from(
    { length: 17 },
    (_, index) => currentYear - 8 + index,
  );
  const hasLegacyGraduationYear =
    Boolean(graduationYear) && !graduationYears.includes(Number(graduationYear));
  const profilePatch = getProfilePatch(
    account,
    displayName,
    college,
    graduationYear,
  );
  const isDirty = Object.keys(profilePatch).length > 0;

  const strength = getProfileStrength(account, hasFieldProfileSelections(fieldProfile));

  useEffect(() => {
    try {
      const key = `aspirova:profile-draft:${user.id}`;
      if (isDirty) sessionStorage.setItem(key, JSON.stringify({ displayName, college, graduationYear }));
      else sessionStorage.removeItem(key);
    } catch {
      // Draft storage is best effort when browser storage is unavailable.
    }
  }, [college, displayName, graduationYear, isDirty, user.id]);

  useEffect(() => {
    if (!isDirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [isDirty]);

  function discardDraft() {
    setDisplayName(account.display_name ?? "");
    setCollege(account.college ?? "");
    setGraduationYear(account.graduation_year?.toString() ?? "");
    setCollegeCountryNotice(false);
  }

  function handleCountrySelect(code: string) {
    if (code !== storedCountryCode && college.trim()) setCollegeCountryNotice(true);
    void storeCountryCode(code, accessToken).catch(() => {
      toast.error("Saved on this device, but we couldn't sync your country to your account.");
    });
    setCollegeEntryMode("list");
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!isDirty) return;

    setSubmitting(true);
    try {
      const updated = await updateAccount(accessToken, profilePatch);
      onAccountChange(updated);
      setDisplayName(updated.display_name ?? "");
      setCollege(updated.college ?? "");
      setGraduationYear(updated.graduation_year?.toString() ?? "");
      toast.success("Profile saved");
    } catch {
      toast.error("We couldn't save your profile. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function focusProfileField(id: string) {
    const field = document.getElementById(id);
    if (!field) return;
    field.focus({ preventScroll: true });
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    field.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
  }

  return (
    <section aria-labelledby="account-profile-heading" className="grid gap-6">
      <SectionHeader id="account-profile-heading" eyebrow="You" title="Profile" description="How you appear on Aspirova, and what we use to tailor your feed." />

      <form onSubmit={handleSubmit} className="grid gap-6">
        <SettingsCard icon={UserRound} title="Personal" description="Your name as it appears across Aspirova.">
          <div className="divide-y divide-border">
            <SettingsRow label="Display name" htmlFor="account-display-name" description="Shown on your account and emails.">
              <Input id="account-display-name" value={displayName} maxLength={80} onChange={(event) => setDisplayName(event.target.value)} placeholder="How should we address you?" />
            </SettingsRow>
            <SettingsRow label="Email" htmlFor="account-email" description="Managed by your sign-in provider.">
              <div className="relative">
                <Input id="account-email" type="email" value={account.email ?? user.email ?? ""} readOnly aria-readonly="true" className="bg-muted/50 pr-10 text-muted-foreground" />
                <Lock className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              </div>
            </SettingsRow>
          </div>
        </SettingsCard>

        <SettingsCard icon={GraduationCap} title="Academics" description="Used to surface programmes and roles for your stage.">
          <div className="divide-y divide-border">
            <SettingsRow label="College" htmlFor="account-college" align="start">
              <div className="grid content-start gap-2.5">
                {!hydrated ? (
                  <Button
                    id="account-college"
                    type="button"
                    variant="outline"
                    disabled
                    className="w-full justify-between font-normal"
                  >
                    <span className="min-w-0 flex-1 truncate text-left">
                      {college.trim() ? college : "Select your college"}
                    </span>
                    <ChevronDown
                      className="shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  </Button>
                ) : collegeEntryMode === "manual" ? (
                  <>
                    <Input
                      id="account-college"
                      value={college}
                      maxLength={120}
                      onChange={(event) => setCollege(event.target.value)}
                      placeholder="Your college"
                    />
                    <Button
                      type="button"
                      variant="link"
                      size="xs"
                      className="min-h-11 w-fit px-0 text-muted-foreground sm:h-auto sm:min-h-0"
                      onClick={() => setCollegeEntryMode("list")}
                    >
                      Choose from list
                    </Button>
                  </>
                ) : selectedCountry ? (
                  <CollegePicker
                    id="account-college"
                    countryCode={selectedCountry.code}
                    value={college}
                    onSelect={(selectedCollege) => setCollege(selectedCollege)}
                    onOther={() => setCollegeEntryMode("manual")}
                  />
                ) : (
                  <>
                    <CountryPicker value={null} onSelect={handleCountrySelect}>
                      <Button
                        id="account-college"
                        type="button"
                        variant="outline"
                        className="w-full justify-between font-normal"
                      >
                        <span>Choose your country</span>
                        <ChevronDown
                          className="shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      </Button>
                    </CountryPicker>
                    <Button
                      type="button"
                      variant="link"
                      size="xs"
                      className="min-h-11 w-fit px-0 text-muted-foreground sm:h-auto sm:min-h-0"
                      onClick={() => setCollegeEntryMode("manual")}
                    >
                      Enter manually
                    </Button>
                  </>
                )}
                {hydrated && selectedCountry && collegeEntryMode === "list" && (
                  <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                    <span>Showing colleges in {selectedCountry.name}</span>
                    <span aria-hidden="true">·</span>
                    <CountryPicker
                      value={selectedCountry.code}
                      onSelect={handleCountrySelect}
                    >
                      <Button
                        type="button"
                        variant="link"
                        size="xs"
                        className="min-h-11 px-0 text-xs text-muted-foreground sm:h-auto sm:min-h-0"
                      >
                        Change
                      </Button>
                    </CountryPicker>
                    <p className="basis-full">Your country is saved to your account, so it follows you across devices.</p>
                  </div>
                )}
                {collegeCountryNotice && selectedCountry && (
                  <div role="status" className="text-xs text-muted-foreground">
                    <p>{college} is still selected. Keep it, or choose a college in {selectedCountry.name}.</p>
                    <div className="mt-1 flex gap-2">
                      <Button type="button" variant="link" size="xs" onClick={() => setCollegeCountryNotice(false)}>Keep it</Button>
                      <Button type="button" variant="link" size="xs" onClick={() => { setCollege(""); setCollegeCountryNotice(false); }}>Choose a new college</Button>
                    </div>
                  </div>
                )}
              </div>
            </SettingsRow>
            <SettingsRow label="Graduation year" htmlFor="account-graduation-year">
              <Select
                value={graduationYear || "none"}
                onValueChange={(value) => setGraduationYear(value === "none" ? "" : value)}
              >
                <SelectTrigger id="account-graduation-year" className="w-full">
                  <SelectValue placeholder="Select your graduation year" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {hasLegacyGraduationYear && (
                    <SelectItem value={graduationYear}>{graduationYear}</SelectItem>
                  )}
                  {graduationYears.map((year) => (
                    <SelectItem key={year} value={year.toString()}>
                      {year}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingsRow>
          </div>
        </SettingsCard>

        {(isDirty || submitting) && (
          <div className="animate-bar-in sticky bottom-[calc(5rem+env(safe-area-inset-bottom))] z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-soft-md md:bottom-4">
            <p className="flex items-center gap-2 text-sm text-foreground"><span className="size-1.5 shrink-0 rounded-full bg-warning" aria-hidden="true" />Unsaved changes</p>
            <div className="ml-auto flex items-center gap-2">
              <Button type="button" variant="ghost" disabled={submitting} onClick={discardDraft}>Discard</Button>
              <Button type="submit" disabled={submitting}>
                {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
                {submitting ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </div>
        )}
      </form>

      <SettingsCard icon={Compass} title="Fields & interests" action={<Button type="button" variant="outline" size="sm" onClick={requestOnboarding}><Pencil aria-hidden="true" />Edit</Button>}>
        {!fieldProfileHydrated ? (
          <p className="py-4 text-sm text-muted-foreground">Loading your field preferences…</p>
        ) : !fieldStream ? (
          <EmptyState compact icon={Compass} title="Tell us your field" description="Add your field and interests to personalise your feed." action={<Button type="button" variant="soft" onClick={requestOnboarding}>Add interests</Button>} />
        ) : (
          <dl className="grid gap-5 py-2 text-sm">
            {[
              { label: "Field", values: [fieldStream.label], empty: "Not selected" },
              { label: "Specialisation", values: fieldDivisionLabels, empty: "Not selected" },
              { label: "Interests", values: fieldInterestLabels, empty: "No interests selected" },
            ].map(({ label, values, empty }) => (
              <div key={label}>
                <dt className="mb-2 text-xs font-medium text-muted-foreground">{label}</dt>
                <dd className="flex flex-wrap gap-2">
                  {values.length ? values.map((value) => <span key={value} className="rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground">{value}</span>) : <span className="text-sm text-muted-foreground">{empty}</span>}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </SettingsCard>

      <SettingsCard icon={Gauge} title="Profile strength" description="Each step makes your recommendations sharper.">
        <div className="mb-6 grid gap-2">
          {fieldProfileHydrated ? (
            <>
              <Meter value={strength.done} max={strength.total} label="Profile strength" valueText={`${strength.done} of ${strength.total} profile steps complete`} tone={strength.done === strength.total ? "success" : "primary"} />
              <p className="tnum text-sm text-muted-foreground">{strength.done} of {strength.total} complete</p>
            </>
          ) : <><Skeleton className="h-1.5 w-full" /><Skeleton className="h-5 w-32" /></>}
        </div>
        <ol>
          {strength.steps.map((step, index) => (
            <li key={step.key} className="relative pb-5 last:pb-0">
              {index < strength.steps.length - 1 && <span className="absolute top-6 bottom-0 left-[11px] w-px bg-border" aria-hidden="true" />}
              {step.key === "field" && !fieldProfileHydrated ? (
                <div className="flex items-center gap-3" aria-label="Loading field preferences"><Skeleton className="size-6 rounded-full" /><Skeleton className="h-5 w-40" /></div>
              ) : (
                <div className="flex items-start gap-3">
                  <span aria-hidden="true" className={cn("relative flex size-6 shrink-0 items-center justify-center rounded-full", step.done ? "bg-primary text-primary-foreground" : "border-2 border-dashed border-muted-foreground/45 bg-card")}>{step.done && <Check className="size-3.5" />}</span>
                  <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-x-3 gap-y-2">
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
                        {step.label}
                        {step.optional && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">Optional</span>}
                        {step.done && <span className="sr-only"> — complete</span>}
                      </p>
                      {!step.done && <p className="mt-1 text-sm text-muted-foreground">{step.reason}</p>}
                    </div>
                    {!step.done && (
                      step.key === "display_name" || step.key === "college" || step.key === "graduation_year" ? (
                        <Button type="button" variant="soft" size="sm" onClick={() => focusProfileField(step.key === "display_name" ? "account-display-name" : step.key === "college" ? "account-college" : "account-graduation-year")}>{`Add ${step.label.toLowerCase()}`}</Button>
                      ) : step.key === "field" ? (
                        <Button type="button" variant="soft" size="sm" onClick={requestOnboarding}>Add interests</Button>
                      ) : (
                        <Button asChild variant="soft" size="sm"><Link href={step.key === "skills" ? "/resume" : "/account?section=resume"}>{step.key === "skills" ? "Add skills" : "Add resume"}</Link></Button>
                      )
                    )}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ol>
      </SettingsCard>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-xl border border-border bg-card px-5 py-3 text-sm shadow-soft sm:px-6">
        <p className="text-muted-foreground">Invite code {account.invite_code && <span className="tnum ml-2 font-mono font-medium text-foreground">{account.invite_code}</span>}</p>
        <Button asChild variant="link"><Link href="/referral">Open referrals →</Link></Button>
      </div>
    </section>
  );
}
