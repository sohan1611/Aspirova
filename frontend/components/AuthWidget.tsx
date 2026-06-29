"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useSession } from "@/lib/useSession";

export default function AuthWidget() {
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [message, setMessage] = useState<string | null>(null);
  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    const { error } =
      mode === "signin"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password });

    if (error) {
      setMessage(error.message);
    } else if (mode === "signup") {
      setMessage("Check your email to confirm your account.");
    }
  }

  if (session) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <span className="text-gray-600">{session.user.email}</span>
        <button
          onClick={() => supabase.auth.signOut()}
          className="rounded border px-3 py-1 hover:bg-gray-100"
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-center gap-2 text-sm">
      <input
        type="email"
        required
        placeholder="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="rounded border px-2 py-1"
      />
      <input
        type="password"
        required
        minLength={6}
        placeholder="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        className="rounded border px-2 py-1"
      />
      <button type="submit" className="rounded bg-black px-3 py-1 text-white">
        {mode === "signin" ? "Sign in" : "Sign up"}
      </button>
      <button
        type="button"
        onClick={() => {
          setMode(mode === "signin" ? "signup" : "signin");
          setMessage(null);
        }}
        className="text-gray-500 underline"
      >
        {mode === "signin" ? "Need an account?" : "Have an account?"}
      </button>
      {message && <span className="text-red-600">{message}</span>}
    </form>
  );
}
