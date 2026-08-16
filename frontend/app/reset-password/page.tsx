"use client";

import { AlertCircle, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MIN_PASSWORD_LENGTH } from "@/lib/password";
import { createClient } from "@/lib/supabase/client";
import { useSessionState } from "@/lib/useSession";

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10">
      <Card className="mx-auto max-w-md">{children}</Card>
    </main>
  );
}

export default function ResetPasswordPage() {
  const { session, resolved } = useSessionState();
  const router = useRouter();
  const supabase = createClient();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirmPassword) {
      setError("Those passwords do not match.");
      return;
    }

    setSaving(true);
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) {
        setError(updateError.message);
        return;
      }
      setDone(true);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "We couldn't update your password. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  // The reset link carries a PKCE code that has to be exchanged before a
  // session exists. Showing "expired" during that exchange would tell the user
  // their working link is broken, so wait for a settled answer first.
  if (!resolved) {
    return (
      <Shell>
        <CardContent
          className="flex items-center justify-center gap-3 py-10"
          role="status"
          aria-label="Checking your reset link"
        >
          <Loader2 className="size-5 animate-spin text-primary" aria-hidden="true" />
          <span className="text-sm text-muted-foreground">
            Checking your reset link…
          </span>
        </CardContent>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <CardHeader>
          <CheckCircle2 className="size-9 text-primary" aria-hidden="true" />
          <CardTitle className="font-serif text-2xl">Password updated</CardTitle>
          <CardDescription>
            You&apos;re signed in with your new password on this device.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Button onClick={() => router.push("/")}>Go to Aspirova</Button>
        </CardFooter>
      </Shell>
    );
  }

  if (!session) {
    return (
      <Shell>
        <CardHeader>
          <AlertCircle className="size-9 text-destructive" aria-hidden="true" />
          <CardTitle className="font-serif text-2xl">
            This reset link is invalid or has expired
          </CardTitle>
          <CardDescription>
            Reset links can only be used once, and they stop working after a
            while. Request a new one from the sign-in form.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <HeaderAuth triggerLabel="Sign in" />
        </CardFooter>
      </Shell>
    );
  }

  return (
    <Shell>
      <CardHeader>
        <KeyRound className="size-9 text-primary" aria-hidden="true" />
        <CardTitle className="font-serif text-2xl">Choose a new password</CardTitle>
        <CardDescription>
          {`Setting a new password for ${session.user.email ?? "your account"}.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} noValidate className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="reset-password">New password</Label>
            <Input
              id="reset-password"
              type="password"
              minLength={MIN_PASSWORD_LENGTH}
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <p className="text-sm text-muted-foreground">
              {`Use at least ${MIN_PASSWORD_LENGTH} characters.`}
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="reset-password-confirm">Confirm new password</Label>
            <Input
              id="reset-password-confirm"
              type="password"
              minLength={MIN_PASSWORD_LENGTH}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}

          <div>
            <Button type="submit" disabled={saving || !password || !confirmPassword}>
              {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
              {saving ? "Updating…" : "Update password"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Shell>
  );
}
