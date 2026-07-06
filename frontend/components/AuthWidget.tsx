"use client";

import { Eye, EyeOff, Loader2, MailCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase/client";
import { useSession } from "@/lib/useSession";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function AuthWidget() {
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [touched, setTouched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [checkEmail, setCheckEmail] = useState(false);
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
  const passwordInvalid = touched && password.length < 6;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    setFormError(null);

    if (!EMAIL_PATTERN.test(email) || password.length < 6) {
      return;
    }

    setLoading(true);
    try {
      const { error } =
        mode === "signin"
          ? await supabase.auth.signInWithPassword({ email, password })
          : await supabase.auth.signUp({ email, password });

      if (error) {
        setFormError(error.message);
      } else if (mode === "signup") {
        setCheckEmail(true);
      }
    } finally {
      setLoading(false);
    }
  }

  if (checkEmail) {
    return (
      <div className="flex flex-col items-center gap-2 py-4 text-center">
        <MailCheck className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="font-medium text-foreground">Check your email</p>
        <p className="text-sm text-muted-foreground">
          We sent a confirmation link to {email}.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
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
        <Label htmlFor="auth-password">Password</Label>
        <div className="relative">
          <Input
            id="auth-password"
            type={showPassword ? "text" : "password"}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={passwordInvalid || undefined}
            className="pr-9"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {passwordInvalid && (
          <p className="text-sm text-destructive">Password must be at least 6 characters.</p>
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
