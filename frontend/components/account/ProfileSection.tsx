"use client";

import type { User } from "@supabase/supabase-js";
import { CalendarDays, ExternalLink, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import AccountAvatar from "@/components/account/AccountAvatar";
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
import { updateAccount } from "@/lib/api";
import { formatDate } from "@/lib/date";
import type { AccountMe } from "@/lib/types";

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

export default function ProfileSection({
  account,
  accessToken,
  user,
  onAccountChange,
}: ProfileSectionProps) {
  const [displayName, setDisplayName] = useState(account.display_name ?? "");
  const [college, setCollege] = useState(account.college ?? "");
  const [graduationYear, setGraduationYear] = useState(
    account.graduation_year?.toString() ?? "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [completionNudgeVisible, setCompletionNudgeVisible] = useState(true);
  const completedProfileFields = [
    Boolean(account.display_name?.trim()),
    Boolean(account.college?.trim()),
    account.graduation_year !== null,
  ].filter(Boolean).length;
  const profileCompletion = (completedProfileFields / 3) * 100;
  const showCompletionNudge = completionNudgeVisible && profileCompletion < 100;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedName = displayName.trim() || null;
    const normalizedCollege = college.trim() || null;
    const normalizedYear = graduationYear ? Number(graduationYear) : null;

    if (
      normalizedYear !== null &&
      (!Number.isInteger(normalizedYear) || normalizedYear < 2000 || normalizedYear > 2100)
    ) {
      toast.error("Graduation year must be between 2000 and 2100.");
      return;
    }

    const patch: Partial<
      Pick<AccountMe, "display_name" | "college" | "graduation_year">
    > = {};
    if (normalizedName !== account.display_name) patch.display_name = normalizedName;
    if (normalizedCollege !== account.college) patch.college = normalizedCollege;
    if (normalizedYear !== account.graduation_year) patch.graduation_year = normalizedYear;

    if (Object.keys(patch).length === 0) {
      toast.message("Your profile is already up to date.");
      return;
    }

    setSubmitting(true);
    try {
      const updated = await updateAccount(accessToken, patch);
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
                    ({completedProfileFields} of 3)
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
              aria-valuemax={3}
              aria-valuenow={completedProfileFields}
              aria-valuetext={`${completedProfileFields} of 3 profile details complete`}
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
            <div className="grid gap-2.5">
              <Label className="eyebrow" htmlFor="account-college">
                College
              </Label>
              <Input
                id="account-college"
                value={college}
                maxLength={120}
                onChange={(event) => setCollege(event.target.value)}
                placeholder="Your college"
              />
            </div>
            <div className="grid gap-2.5">
              <Label className="eyebrow" htmlFor="account-graduation-year">
                Graduation year
              </Label>
              <Input
                id="account-graduation-year"
                type="number"
                min={2000}
                max={2100}
                inputMode="numeric"
                value={graduationYear}
                onChange={(event) => setGraduationYear(event.target.value)}
                placeholder="2027"
              />
            </div>
          </div>

          <div className="flex justify-end border-t border-border pt-6">
            <Button type="submit" disabled={submitting}>
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
