"use client";

import type { User } from "@supabase/supabase-js";
import { Loader2, LogOut, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { PasswordInput } from "@/components/PasswordInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { exportAccountData } from "@/lib/api";
import { passwordUpdateErrorMessage } from "@/lib/authErrors";
import { signOutWithFeedback } from "@/lib/signOut";
import { MIN_PASSWORD_LENGTH } from "@/lib/password";
import { createClient } from "@/lib/supabase/client";

function providersFor(user: User | null | undefined): string[] {
  const identityProviders = Array.isArray(user?.identities)
    ? user.identities
        .map((identity) => identity?.provider)
        .filter((provider): provider is string => typeof provider === "string")
    : [];
  const metadataProviders: unknown = user?.app_metadata?.providers;
  const fallbackProviders = Array.isArray(metadataProviders)
    ? metadataProviders.filter(
        (provider): provider is string => typeof provider === "string",
      )
    : [];
  const primaryProvider: unknown = user?.app_metadata?.provider;

  return Array.from(
    new Set([
      ...identityProviders,
      ...fallbackProviders,
      ...(typeof primaryProvider === "string" ? [primaryProvider] : []),
    ]),
  );
}

function providerLabel(provider: string): string {
  if (provider === "github") return "GitHub";
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

export default function SecuritySection({
  user,
  accessToken,
}: {
  user: User | null | undefined;
  accessToken: string;
}) {
  const supabase = createClient();
  const providers = providersFor(user);
  const canChangePassword = providers.includes("email");
  const [password, setPassword] = useState("");
  const [updatingPassword, setUpdatingPassword] = useState(false);

  const [signingOut, setSigningOut] = useState<"local" | "global" | null>(null);
  const [downloading, setDownloading] = useState(false);
  const deletionHref = "mailto:support@aspirova.org?subject=" +
    encodeURIComponent("Account deletion request") + "&body=" +
    encodeURIComponent("Please delete my Aspirova account.\nAccount email: " + (user?.email ?? ""));

  async function handleSignOut(scope?: "global") {
    if (signingOut) return;
    setSigningOut(scope ?? "local");
    try {
      await signOutWithFeedback(supabase, scope);
    } finally {
      setSigningOut(null);
    }
  }

  async function handleDownload() {
    if (downloading) return;
    setDownloading(true);
    try {
      const data = await exportAccountData(accessToken);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "aspirova-data-" + new Date().toISOString().slice(0, 10) + ".json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      toast.error("We couldn't download your data. Please try again.");
    } finally {
      setDownloading(false);
    }
  }

  async function handlePasswordSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD_LENGTH) {
      toast.error(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setUpdatingPassword(true);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      setPassword("");
      toast.success("Password updated");
    } catch (error: unknown) {
      toast.error(passwordUpdateErrorMessage(error, "account"));
    } finally {
      setUpdatingPassword(false);
    }
  }

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-2xl">Security</CardTitle>
          <CardDescription>Sign-in and password.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6">
          <section aria-labelledby="account-your-data" className="grid gap-3">
            <h3 id="account-your-data" className="font-medium text-foreground">Your data</h3>
            <div>
              <Button variant="outline" disabled={downloading} onClick={() => void handleDownload()}>
                {downloading && <Loader2 className="animate-spin" aria-hidden="true" />}
                {downloading ? "Downloading…" : "Download my data"}
              </Button>
            </div>
          </section>
          <Separator />
          {canChangePassword && (
            <>
              <form onSubmit={handlePasswordSubmit} className="grid gap-4">
                <div>
                  <h3 className="font-medium text-foreground">Change password</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {`Use at least ${MIN_PASSWORD_LENGTH} characters for your new password.`}
                  </p>
                </div>
                <div className="grid max-w-sm gap-2">
                  <Label htmlFor="account-new-password">New password</Label>
                  <PasswordInput
                    id="account-new-password"
                    minLength={MIN_PASSWORD_LENGTH}
                    autoComplete="new-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </div>
                <div>
                  <Button type="submit" disabled={updatingPassword || !password}>
                    {updatingPassword && (
                      <Loader2 className="animate-spin" aria-hidden="true" />
                    )}
                    {updatingPassword ? "Updating…" : "Update password"}
                  </Button>
                </div>
              </form>
              <Separator />
            </>
          )}

          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-5 text-primary" aria-hidden="true" />
              <h3 className="font-medium text-foreground">Connected accounts</h3>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Providers currently linked to your account.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {providers.map((provider) => (
                <Badge key={provider} variant="secondary">
                  {providerLabel(provider)}
                </Badge>
              ))}
            </div>
          </div>

          <Separator />

          <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <h3 className="font-medium text-foreground">Sign out</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                End your session on this device.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={signingOut !== null} onClick={() => void handleSignOut()}>
                <LogOut aria-hidden="true" />
                {signingOut === "local" ? "Signing out…" : "Sign out"}
              </Button>
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline" disabled={signingOut !== null}>Sign out of all devices</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Sign out of all devices?</DialogTitle>
                    <DialogDescription>
                      This ends your session on every device, including this one. Other devices may take a short time to sign out.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogClose asChild>
                      <Button variant="outline">Cancel</Button>
                    </DialogClose>
                    <Button
                      disabled={signingOut !== null}
                      onClick={() => void handleSignOut("global")}
                    >
                      {signingOut === "global" ? "Signing out…" : "Sign out of all devices"}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-destructive/35 bg-destructive/5">
        <CardHeader>
          <CardTitle className="font-serif text-xl text-destructive">
            Danger zone
          </CardTitle>
          <CardDescription>
            Account deletion permanently removes your profile and saved data.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="destructive">
                <Trash2 aria-hidden="true" />
                Request account deletion
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Request account deletion</DialogTitle>
                <DialogDescription>
                  Account deletion isn&apos;t self-serve yet. Email us from the address on your account and we&apos;ll remove your profile, saved data and resume. If you&apos;re on a paid plan, cancel it first under Subscription so it doesn&apos;t renew. Encrypted backup copies are kept for a limited time, as described in our{" "}
                  <Link href="/privacy" className="font-medium text-foreground underline underline-offset-4">Privacy Policy</Link>.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">Close</Button>
                </DialogClose>
                <Button asChild><a href={deletionHref}>Email deletion request</a></Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardContent>
      </Card>
    </div>
  );
}
