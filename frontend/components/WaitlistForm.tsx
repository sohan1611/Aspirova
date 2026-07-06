"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { joinWaitlist } from "@/lib/api";

export default function WaitlistForm({
  planLabel,
  highlight,
}: {
  planLabel: string;
  highlight?: boolean;
}) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [joined, setJoined] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await joinWaitlist(email);
      setJoined(true);
      toast(`You're on the ${planLabel} waitlist`, {
        description: "We'll email you when checkout opens.",
      });
    } catch {
      toast.error("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  if (joined) {
    return (
      <p className="w-full text-center text-sm font-medium text-primary">
        You&apos;re on the list ✓
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-2">
      <Input
        type="email"
        required
        placeholder="you@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        aria-label={`Email for ${planLabel} waitlist`}
      />
      <Button type="submit" variant={highlight ? "default" : "outline"} disabled={loading} className="w-full">
        {loading && <Loader2 className="animate-spin" />}
        Join the waitlist
      </Button>
    </form>
  );
}
