"use client";

import { Loader2, MailCheck, UserCheck } from "lucide-react";
import { useState } from "react";
import { PasswordInput } from "@/components/PasswordInput";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MIN_PASSWORD_LENGTH } from "@/lib/password";
import { createClient } from "@/lib/supabase/client";
import { useSession } from "@/lib/useSession";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
type OAuthProvider = "google" | "github";

/** A terminal message that replaces the form once an action succeeds. */
type AuthNotice = "check-email" | "already-registered" | "reset-sent";

function GoogleIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.62z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M12 .5A11.5 11.5 0 0 0 8.36 22.9c.58.11.79-.25.79-.56v-2.02c-3.22.7-3.9-1.38-3.9-1.38-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.78 1.2 1.78 1.2 1.04 1.77 2.72 1.26 3.38.96.11-.75.41-1.26.74-1.55-2.57-.29-5.27-1.29-5.27-5.72 0-1.26.45-2.3 1.19-3.11-.12-.29-.52-1.47.11-3.07 0 0 .97-.31 3.18 1.19A11.05 11.05 0 0 1 12 6.05c.98 0 1.96.13 2.88.39 2.2-1.5 3.17-1.19 3.17-1.19.63 1.6.23 2.78.11 3.07.74.81 1.19 1.85 1.19 3.11 0 4.45-2.7 5.43-5.28 5.71.42.36.79 1.08.79 2.17v3.03c0 .31.21.68.8.56A11.5 11.5 0 0 0 12 .5z"
      />
    </svg>
  );
}

const SOCIAL_PROVIDERS: Array<{
  provider: OAuthProvider;
  label: string;
  Icon: () => React.JSX.Element;
}> = [
  { provider: "google", label: "Continue with Google", Icon: GoogleIcon },
  { provider: "github", label: "Continue with GitHub", Icon: GitHubIcon },
];

export default function AuthWidget() {
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [touched, setTouched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [oauthLoadingProvider, setOauthLoadingProvider] = useState<OAuthProvider | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<AuthNotice | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const supabase = createClient();

  if (session) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <span className="hidden max-w-48 truncate text-muted-foreground md:inline">
          {session.user.email}
        </span>
        <Button variant="outline" size="sm" onClick={() => supabase.auth.signOut()}>
          Sign out
        </Button>
      </div>
    );
  }

  const emailInvalid = touched && !EMAIL_PATTERN.test(email);
  const signInPasswordMissing = touched && mode === "signin" && password.length === 0;
  const signUpPasswordInvalid =
    touched && mode === "signup" && password.length < MIN_PASSWORD_LENGTH;
  const passwordInvalid = signInPasswordMissing || signUpPasswordInvalid;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    setFormError(null);

    const passwordBlocked =
      mode === "signin"
        ? password.length === 0
        : password.length < MIN_PASSWORD_LENGTH;

    if (!EMAIL_PATTERN.test(email) || passwordBlocked) {
      return;
    }

    setLoading(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) {
          setFormError(error.message);
        }
        return;
      }

      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo:
            typeof window !== "undefined" ? window.location.origin : undefined,
        },
      });

      if (error) {
        setFormError(error.message);
        return;
      }

      // Supabase answers an already-registered address with success and a decoy
      // user so signup cannot be used to enumerate accounts — but it sends no
      // email, so claiming we did would be a lie. The empty identities array is
      // what distinguishes that case.
      const identities = data.user?.identities;
      if (Array.isArray(identities) && identities.length === 0) {
        setNotice("already-registered");
        return;
      }

      // Unrecognised shape: fall back rather than guess. A wrong "already
      // registered" would block a genuine signup.
      setNotice("check-email");
    } finally {
      setLoading(false);
    }
  }

  async function handleForgotPassword() {
    setFormError(null);

    if (!EMAIL_PATTERN.test(email)) {
      setFormError("Enter your email address above, then choose Forgot password.");
      return;
    }

    setResetLoading(true);
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo:
          typeof window !== "undefined"
            ? `${window.location.origin}/reset-password`
            : undefined,
      });

      if (error) {
        setFormError(error.message);
      } else {
        setNotice("reset-sent");
      }
    } catch (error) {
      setFormError(
        error instanceof Error ? error.message : "Unable to send the reset link.",
      );
    } finally {
      setResetLoading(false);
    }
  }

  async function handleOAuthSignIn(provider: OAuthProvider) {
    setFormError(null);
    setOauthLoadingProvider(provider);

    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider,
        options: {
          redirectTo: typeof window !== "undefined" ? window.location.origin : undefined,
        },
      });

      if (error) {
        setFormError(error.message);
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Unable to start social sign-in.");
    } finally {
      setOauthLoadingProvider(null);
    }
  }

  if (notice === "already-registered") {
    return (
      <div className="flex flex-col items-center gap-2 py-4 text-center">
        <UserCheck className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="font-medium text-foreground">That email already has an account</p>
        {/* Built as one expression: JSX drops the space between {email} and
            adjacent text here, which renders "…@gmail.comis already". */}
        <p className="text-sm text-muted-foreground">
          {`${email} is already registered, so we didn't send a new confirmation link. Sign in instead, or reset your password if you've forgotten it.`}
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => {
            setNotice(null);
            setMode("signin");
            setPassword("");
            setTouched(false);
            setFormError(null);
          }}
        >
          Sign in instead
        </Button>
      </div>
    );
  }

  if (notice === "reset-sent") {
    return (
      <div className="flex flex-col items-center gap-2 py-4 text-center">
        <MailCheck className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="font-medium text-foreground">Check your email</p>
        <p className="text-sm text-muted-foreground">
          {`If ${email} has an account, a password reset link is on its way.`}
        </p>
      </div>
    );
  }

  if (notice === "check-email") {
    return (
      <div className="flex flex-col items-center gap-2 py-4 text-center">
        <MailCheck className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="font-medium text-foreground">Check your email</p>
        <p className="text-sm text-muted-foreground">
          {`We sent a confirmation link to ${email}.`}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <div className="grid gap-2">
        {SOCIAL_PROVIDERS.map(({ provider, label, Icon }) => {
          const isLoading = oauthLoadingProvider === provider;

          return (
            <Button
              key={provider}
              type="button"
              variant="outline"
              className="w-full"
              disabled={loading || oauthLoadingProvider !== null}
              onClick={() => void handleOAuthSignIn(provider)}
            >
              {isLoading ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Icon />}
              {label}
            </Button>
          );
        })}
      </div>

      <div className="relative flex items-center py-1 text-xs text-muted-foreground">
        <div className="h-px flex-1 bg-border" aria-hidden="true" />
        <span className="px-3">or continue with email</span>
        <div className="h-px flex-1 bg-border" aria-hidden="true" />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="auth-email">Email</Label>
        <Input
          id="auth-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={emailInvalid || undefined}
        />
        {emailInvalid && (
          <p className="text-sm text-destructive">Enter a valid email address.</p>
        )}
      </div>

      <div className="grid gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="auth-password">Password</Label>
          {mode === "signin" && (
            <button
              type="button"
              onClick={() => void handleForgotPassword()}
              disabled={loading || resetLoading || oauthLoadingProvider !== null}
              className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline disabled:opacity-60"
            >
              {resetLoading ? "Sending…" : "Forgot password?"}
            </button>
          )}
        </div>
        <PasswordInput
          id="auth-password"
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-invalid={passwordInvalid || undefined}
        />
        {signInPasswordMissing && (
          <p className="text-sm text-destructive">Enter your password.</p>
        )}
        {signUpPasswordInvalid && (
          <p className="text-sm text-destructive">
            {`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`}
          </p>
        )}
      </div>

      {formError && <p className="text-sm text-destructive">{formError}</p>}

      <Button type="submit" disabled={loading} className="w-full">
        {loading && <Loader2 className="animate-spin" />}
        {mode === "signin" ? "Sign in" : "Sign up"}
      </Button>

      <button
        type="button"
        onClick={() => {
          setMode(mode === "signin" ? "signup" : "signin");
          setFormError(null);
          setTouched(false);
        }}
        className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        {mode === "signin" ? "Need an account? Sign up" : "Have an account? Sign in"}
      </button>
    </form>
  );
}
