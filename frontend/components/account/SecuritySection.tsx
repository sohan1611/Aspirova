"use client";

import type { User } from "@supabase/supabase-js";
import { Loader2, LogOut, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { createClient } from "@/lib/supabase/client";

function providersFor(user: User): string[] {
  const identityProviders = user.identities?.map((identity) => identity.provider) ?? [];
  const metadataProviders: unknown = user.app_metadata?.providers;
  const fallbackProviders = Array.isArray(metadataProviders)
    ? metadataProviders.filter(
        (provider): provider is string => typeof provider === "string",
      )
    : [];
  const primaryProvider: unknown = user.app_metadata?.provider;

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

export default function SecuritySection({ user }: { user: User }) {
  const supabase = createClient();
  const providers = providersFor(user);
  const canChangePassword = providers.includes("email");
  const [password, setPassword] = useState("");
  const [updatingPassword, setUpdatingPassword] = useState(false);

  async function handlePasswordSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < 6) {
      toast.error("Password must be at least 6 characters.");
      return;
    }

    setUpdatingPassword(true);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      setPassword("");
      toast.success("Password updated");
    } catch (error: unknown) {
      toast.error(
        error instanceof Error
          ? error.message
          : "We couldn't update your password. Please try again.",
      );
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
          {canChangePassword && (
            <>
              <form onSubmit={handlePasswordSubmit} className="grid gap-4">
                <div>
                  <h3 className="font-medium text-foreground">Change password</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Use at least 6 characters for your new password.
                  </p>
                </div>
                <div className="grid max-w-sm gap-2">
                  <Label htmlFor="account-new-password">New password</Label>
                  <Input
                    id="account-new-password"
                    type="password"
                    minLength={6}
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
            <Button variant="outline" onClick={() => void supabase.auth.signOut()}>
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
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
                Delete account
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete your account</DialogTitle>
                <DialogDescription>
                  Account deletion isn&apos;t self-serve yet. Email{" "}
                  <a
                    href="mailto:support@aspirova.org"
                    className="font-medium text-foreground underline underline-offset-4"
                  >
                    support@aspirova.org
                  </a>{" "}
                  and we&apos;ll remove your account and data.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">Close</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardContent>
      </Card>
    </div>
  );
}
