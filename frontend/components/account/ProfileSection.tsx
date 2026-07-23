"use client";

import type { User } from "@supabase/supabase-js";
import { CalendarDays, ChevronDown, ExternalLink, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import AccountAvatar from "@/components/account/AccountAvatar";
import { CollegePicker } from "@/components/CollegePicker";
import { CountryPicker } from "@/components/CountryPicker";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { updateAccount } from "@/lib/api";
import { storeCountryCode, useStoredCountryCode } from "@/lib/country";
import { getCountry } from "@/lib/countries";
import { formatDate } from "@/lib/date";
import { useFieldProfile } from "@/lib/fieldProfile";
import { requestOnboarding } from "@/lib/interests";
import {
  getProfileCompleteness,
  PROFILE_COMPLETENESS_TOTAL,
} from "@/lib/profileCompleteness";
import { getDivision, getStream, interestsFor } from "@/lib/taxonomy";
import type { AccountMe } from "@/lib/types";
import { useHydrated } from "@/lib/useHydrated";

interface ProfileSectionProps {
  account: AccountMe;
  accessToken: string;
  user: User;
  onAccountChange: (account: AccountMe) => void;
}

function avatarUrlFor(user: User): string | null {
  const avatarUrl: unknown = user.user_metadata?.avatar_url;
  return typeof avatarUrl === "string" ? avatarUrl : null;
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

export default function ProfileSection({
  account,
  accessToken,
  user,
  onAccountChange,
}: ProfileSectionProps) {
  const [displayName, setDisplayName] = useState(account.display_name ?? "");
  const [college, setCollege] = useState(account.college ?? "");
  const [collegeEntryMode, setCollegeEntryMode] = useState<"list" | "manual">("list");
  const [graduationYear, setGraduationYear] = useState(
    account.graduation_year?.toString() ?? "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [completionNudgeVisible, setCompletionNudgeVisible] = useState(true);
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
  const { completedFields, percentage: profileCompletion } = getProfileCompleteness(account);
  const showCompletionNudge =
    completionNudgeVisible && completedFields < PROFILE_COMPLETENESS_TOTAL;
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

  function handleCountrySelect(code: string) {
    storeCountryCode(code);
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-2xl">Profile</CardTitle>
        <CardDescription>Your name and academic details.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-7">
        {showCompletionNudge && (
          <div className="rounded-lg border border-border bg-muted/40 px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  Complete your profile{" "}
                  <span className="tnum text-muted-foreground">
                    ({completedFields} of {PROFILE_COMPLETENESS_TOTAL})
                  </span>
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Add your remaining academic details to get more from Aspirova.
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                className="-mr-1 -mt-1 shrink-0 text-muted-foreground"
                onClick={() => setCompletionNudgeVisible(false)}
                aria-label="Dismiss profile completion reminder"
              >
                <X aria-hidden="true" />
              </Button>
            </div>
            <div
              className="mt-3 h-1.5 overflow-hidden rounded-full bg-border/70"
              role="progressbar"
              aria-label="Profile completeness"
              aria-valuemin={0}
              aria-valuemax={PROFILE_COMPLETENESS_TOTAL}
              aria-valuenow={completedFields}
              aria-valuetext={`${completedFields} of ${PROFILE_COMPLETENESS_TOTAL} profile details complete`}
            >
              <div
                className="h-full rounded-full bg-muted-foreground/45"
                style={{ width: `${profileCompletion}%` }}
              />
            </div>
          </div>
        )}

        <div className="flex items-center gap-4">
          <AccountAvatar
            email={account.email ?? user.email}
            avatarUrl={avatarUrlFor(user)}
            className="size-16 text-xl"
          />
          <div className="min-w-0">
            <p className="truncate font-medium text-foreground">
              {account.display_name || account.email || "Aspirova member"}
            </p>
            <p className="truncate text-sm text-muted-foreground">
              {account.email ?? user.email}
            </p>
          </div>
        </div>

        <Separator />

        <form onSubmit={handleSubmit} className="grid gap-6">
          <div className="grid gap-2.5">
            <Label className="eyebrow" htmlFor="account-display-name">
              Display name
            </Label>
            <Input
              id="account-display-name"
              value={displayName}
              maxLength={80}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="How should we address you?"
            />
          </div>

          <div className="grid gap-2.5">
            <Label className="eyebrow" htmlFor="account-email">
              Email
            </Label>
            <Input
              id="account-email"
              type="email"
              value={account.email ?? user.email ?? ""}
              readOnly
              aria-readonly="true"
              className="bg-muted/50 text-muted-foreground"
            />
          </div>

          <div className="grid gap-6 sm:grid-cols-2">
            <div className="grid gap-2.5 content-start">
              <Label className="eyebrow" htmlFor="account-college">
                College
              </Label>
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
                    className="h-auto w-fit px-0 text-muted-foreground"
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
                    className="h-auto w-fit px-0 text-muted-foreground"
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
                      className="h-auto px-0 text-xs text-muted-foreground"
                    >
                      Change
                    </Button>
                  </CountryPicker>
                </div>
              )}
            </div>
            <div className="grid gap-2.5 content-start">
              <Label className="eyebrow" htmlFor="account-graduation-year">
                Graduation year
              </Label>
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
            </div>
          </div>

          <section
            aria-labelledby="account-field-interests"
            className="grid gap-3 rounded-lg border border-border bg-muted/20 p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p id="account-field-interests" className="eyebrow">
                  Fields &amp; interests
                </p>
                {!fieldProfileHydrated ? (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Loading your field preferences…
                  </p>
                ) : !fieldStream ? (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Add your field and interests to personalise your feed.
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Used to personalise the opportunities you see first.
                  </p>
                )}
              </div>
              <Button type="button" variant="outline" size="sm" onClick={requestOnboarding}>
                Edit
              </Button>
            </div>

            {fieldProfileHydrated && fieldStream && (
              <dl className="grid gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">Field</dt>
                  <dd className="mt-1 font-medium text-foreground">{fieldStream.label}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Specialisation</dt>
                  <dd className="mt-1 font-medium text-foreground">
                    {fieldDivisionLabels.length > 0
                      ? fieldDivisionLabels.join(", ")
                      : "Not selected"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Interests</dt>
                  <dd className="mt-1 font-medium text-foreground">
                    {fieldInterestLabels.length > 0
                      ? fieldInterestLabels.join(", ")
                      : "No interests selected"}
                  </dd>
                </div>
              </dl>
            )}
          </section>

          <div className="flex justify-end border-t border-border pt-6">
            <Button type="submit" disabled={submitting || !isDirty}>
              {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
              {submitting ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>

        <Separator />

        <div className="grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <p className="text-muted-foreground">Member since</p>
            <p className="mt-1 flex items-center gap-2 font-medium text-foreground">
              <CalendarDays className="size-4 text-primary" aria-hidden="true" />
              {formatDate(account.created_at, "long")}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Your referral link</p>
            <Button asChild variant="link" className="mt-1 h-auto justify-start p-0">
              <Link href="/referral">
                {account.invite_code ? `Invite code: ${account.invite_code}` : "Open referrals"}
                <ExternalLink aria-hidden="true" />
              </Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
