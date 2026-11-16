"use client";

import type { User } from "@supabase/supabase-js";
import { Download, KeyRound, Loader2, LockKeyhole, LogOut, Mail, MonitorSmartphone, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { PasswordInput } from "@/components/PasswordInput";
import AuthWidget, { GitHubIcon, GoogleIcon } from "@/components/AuthWidget";
import { ConfirmDialog, SectionHeader, SettingsCard, SettingsRow, StatusPill } from "@/components/account/primitives";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { providersFor, providerLabel } from "@/lib/authProviders";
import { AccountDeletionError, deleteAccount, exportAccountData } from "@/lib/api";
import { clearDeletedAccountStorage, tokenIssuedAt } from "@/lib/accountDeletion";
import { passwordUpdateErrorMessage } from "@/lib/authErrors";
import { signOutWithFeedback } from "@/lib/signOut";
import { MIN_PASSWORD_LENGTH } from "@/lib/password";
import { createClient } from "@/lib/supabase/client";

export default function SecuritySection({
  user,
  accessToken,
}: {
  user: User | null | undefined;
  accessToken: string;
}) {
  const supabase = createClient();
  const router = useRouter();
  const providers = providersFor(user);
  const canChangePassword = providers.includes("email");
  const [password, setPassword] = useState("");
  const [updatingPassword, setUpdatingPassword] = useState(false);

  const [signingOut, setSigningOut] = useState<"local" | "global" | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [signOutDialogOpen, setSignOutDialogOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deletionError, setDeletionError] = useState<string | null>(null);
  const [reauthRequired, setReauthRequired] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const deleteInFlight = useRef(false);
  const resumedReauth = useRef(false);

  const handleDelete = useCallback(async (token: string) => {
    if (deleteInFlight.current) return;
    deleteInFlight.current = true;
    setDeleting(true);
    setDeletionError(null);
    try {
      await deleteAccount(token);
    } catch (error) {
      if (error instanceof AccountDeletionError && error.detail === "active_subscription") {
        setDeletionError("Cancel your subscription under Subscription first so it will not renew. Then return here to delete your account.");
      } else if (error instanceof AccountDeletionError && error.detail === "reauth_required") {
        setReauthRequired(true);
        // OAuth leaves this page. Resume only this confirmed request, for this
        // same account, within ten minutes. No email or credentials are stored.
        try {
          sessionStorage.setItem("aspirova:deletion-reauth", JSON.stringify({ userId: user?.id, at: Date.now(), issuedAt: tokenIssuedAt(token) }));
        } catch { /* Inline password sign-in still works without storage. */ }
      } else {
        setDeletionError("We couldn't confirm account deletion. Check your connection and try again.");
      }
      deleteInFlight.current = false;
      setDeleting(false);
      return;
    }
    let signedOut = false;
    try {
      const { error } = await supabase.auth.signOut({ scope: "local" });
      signedOut = !error;
    } catch { /* The identity may already be gone. Clear local data anyway. */ }
    clearDeletedAccountStorage();
    if (!signedOut) {
      // A full navigation also discards the client's in-memory session when
      // revocation was unreachable. The destination displays the success toast.
      window.location.replace("/?account=deleted");
      return;
    }
    toast.success("Your account has been deleted.");
    router.replace("/");
    router.refresh();
  }, [router, supabase, user, setDeletionError, setReauthRequired, setDeleting]);

  useEffect(() => {
    if (resumedReauth.current) return;
    try {
      const raw = sessionStorage.getItem("aspirova:deletion-reauth");
      if (!raw) return;
      const pending = JSON.parse(raw);
      if (pending.userId !== user?.id || typeof pending.at !== "number" || typeof pending.issuedAt !== "number" || Date.now() - pending.at < 0 || Date.now() - pending.at > 600_000) {
        sessionStorage.removeItem("aspirova:deletion-reauth");
        return;
      }
      const issuedAt = tokenIssuedAt(accessToken);
      if (issuedAt === null || issuedAt <= pending.issuedAt) return;
      resumedReauth.current = true;
      sessionStorage.removeItem("aspirova:deletion-reauth");
      void Promise.resolve().then(() => {
        setDeleteOpen(true);
        setConfirmation("DELETE");
        return handleDelete(accessToken);
      });
    } catch { /* A missing or invalid pending request cannot trigger deletion. */ }
  }, [accessToken, handleDelete, user?.id]);

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
      toast.success("Your download has started");
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
    <section aria-labelledby="account-security-heading" className="grid gap-6">
      <SectionHeader id="account-security-heading" eyebrow="Account" title="Security" description="Sign-in methods, sessions and your data." />

      <SettingsCard icon={KeyRound} title="Sign-in methods">
        {providers.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sign-in methods found.</p>
        ) : (
          <ul className="divide-y divide-border">
            {providers.map((provider) => (
              <li key={provider} className="flex items-center gap-3 py-4 first:pt-0 last:pb-0">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  {provider === "google" ? <GoogleIcon /> : provider === "github" ? <GitHubIcon /> : provider === "email" ? <Mail className="size-4" aria-hidden="true" /> : <KeyRound className="size-4" aria-hidden="true" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{providerLabel(provider)}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{provider === "email" ? "Email and password" : "Single sign-on"}</p>
                </div>
                <StatusPill tone="success">Connected</StatusPill>
              </li>
            ))}
          </ul>
        )}
      </SettingsCard>

      {canChangePassword && (
        <form onSubmit={handlePasswordSubmit}>
          <SettingsCard
            icon={LockKeyhole}
            title="Password"
            description={`Use at least ${MIN_PASSWORD_LENGTH} characters for your new password.`}
            footer={
              <div className="flex w-full flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">{!password && "Enter a new password to update it."}</p>
                <Button type="submit" disabled={updatingPassword || !password}>
                  {updatingPassword && <Loader2 className="animate-spin" aria-hidden="true" />}
                  {updatingPassword ? "Updating…" : "Update password"}
                </Button>
              </div>
            }
          >
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
          </SettingsCard>
        </form>
      )}

      <SettingsCard icon={MonitorSmartphone} title="Sessions">
        <div className="divide-y divide-border">
          <SettingsRow label="This device" description="End your session on this device.">
            <div className="sm:flex sm:justify-end">
              <Button variant="outline" disabled={signingOut !== null} onClick={() => void handleSignOut()}>
                {signingOut === "local" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <LogOut aria-hidden="true" />}
                {signingOut === "local" ? "Signing out…" : "Sign out"}
              </Button>
            </div>
          </SettingsRow>
          <SettingsRow label="All devices" description="Signs you out everywhere, including this device.">
            <div className="sm:flex sm:justify-end">
              <Button variant="outline" disabled={signingOut !== null} onClick={() => setSignOutDialogOpen(true)}>
                <LogOut aria-hidden="true" />Sign out everywhere
              </Button>
            </div>
          </SettingsRow>
        </div>
        <ConfirmDialog
          open={signOutDialogOpen}
          onOpenChange={setSignOutDialogOpen}
          tone="default"
          title="Sign out of all devices?"
          description="This ends your session on every device, including this one. Other devices may take a short time to sign out."
          confirmLabel="Sign out of all devices"
          pendingLabel="Signing out…"
          pending={signingOut === "global"}
          onConfirm={() => handleSignOut("global")}
        />
      </SettingsCard>

      <SettingsCard icon={Download} title="Your data" description="Download a copy of everything Aspirova stores about you, as a JSON file.">
        <Button variant="outline" disabled={downloading} onClick={() => void handleDownload()}>
          {downloading ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
          {downloading ? "Downloading…" : "Download my data"}
        </Button>
      </SettingsCard>

      <SettingsCard icon={TriangleAlert} title="Danger zone" tone="danger" description="Account deletion permanently removes your profile and saved data.">
        <SettingsRow label="Delete your account">
          <div className="sm:flex sm:justify-end">
            <Dialog open={deleteOpen} onOpenChange={(open) => {
              if (deleting) return;
              setDeleteOpen(open);
              if (!open) {
                setConfirmation("");
                setReauthRequired(false);
                setDeletionError(null);
                try { sessionStorage.removeItem("aspirova:deletion-reauth"); } catch { /* Storage unavailable. */ }
              }
            }}>
              <DialogTrigger asChild>
                <Button variant="destructive-ghost">
                  <Trash2 aria-hidden="true" />Delete account
                </Button>
              </DialogTrigger>
              <DialogContent className="max-h-[90dvh] overflow-y-auto">
                <DialogHeader>
                  <DialogTitle>Delete your account permanently?</DialogTitle>
                  <DialogDescription>
                    This deletes your profile, saved and tracked listings, saved searches, followed companies, watched programmes, notifications, resume file and embedding, and bug reports. Account access is disabled immediately; failed file or identity cleanup is retried. This cannot be undone. Billing records required by law are kept. Encrypted backups keep 7 daily copies and 4 weekly copies; the migration archive has no automatic expiry. See our{" "}
                    <Link href="/privacy" className="font-medium text-foreground underline underline-offset-4">Privacy Policy</Link>.
                  </DialogDescription>
                </DialogHeader>
                <div className="grid gap-2">
                  <Label htmlFor="delete-confirmation">Type DELETE</Label>
                  <Input id="delete-confirmation" autoComplete="off" value={confirmation} disabled={deleting} onChange={(event) => setConfirmation(event.target.value)} />
                </div>
                {deletionError && <div role="alert" className="grid gap-2 text-sm text-destructive">
                  <p>{deletionError}</p>
                  {deletionError.startsWith("Cancel your subscription") && <Link href="/account?section=subscription" className="underline">Go to Subscription</Link>}
                </div>}
                {reauthRequired && <div className="grid gap-3">
                  <p className="text-sm">Sign in again to confirm it is you. Deletion will retry after you sign in.</p>
                  <AuthWidget reauthenticate expectedUserId={user?.id} onAuthenticated={(token) => {
                    try { sessionStorage.removeItem("aspirova:deletion-reauth"); } catch { /* Storage unavailable. */ }
                    setReauthRequired(false);
                    void handleDelete(token);
                  }} />
                </div>}
                <DialogFooter>
                  <DialogClose asChild>
                    <Button variant="outline" disabled={deleting}>Cancel</Button>
                  </DialogClose>
                  <Button variant="destructive" disabled={confirmation !== "DELETE" || deleting || reauthRequired} onClick={() => void handleDelete(accessToken)}>
                    {deleting && <Loader2 className="animate-spin" aria-hidden="true" />}
                    {deleting ? "Deleting…" : "Delete my account"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </SettingsRow>
      </SettingsCard>
    </section>
  );
}
