"use client";

import type { User } from "@supabase/supabase-js";
import { CalendarDays, ExternalLink, Loader2 } from "lucide-react";
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
        <CardDescription>
          Keep the details Aspirova uses to personalize your experience up to date.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
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

        <form onSubmit={handleSubmit} className="grid gap-5">
          <div className="grid gap-2">
            <Label htmlFor="account-display-name">Display name</Label>
            <Input
              id="account-display-name"
              value={displayName}
              maxLength={80}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="How should we address you?"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="account-email">Email</Label>
            <Input
              id="account-email"
              type="email"
              value={account.email ?? user.email ?? ""}
              readOnly
              aria-readonly="true"
              className="bg-muted/50 text-muted-foreground"
            />
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="account-college">College</Label>
              <Input
                id="account-college"
                value={college}
                maxLength={120}
                onChange={(event) => setCollege(event.target.value)}
                placeholder="Your college"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="account-graduation-year">Graduation year</Label>
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

          <div>
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
              {new Date(account.created_at).toLocaleDateString(undefined, {
                day: "numeric",
                month: "long",
                year: "numeric",
              })}
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
