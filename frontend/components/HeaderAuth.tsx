"use client";

import AuthWidget from "@/components/AuthWidget";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useSession } from "@/lib/useSession";

/**
 * Structural home for auth in the header (Part 3.3): signed-in state stays
 * inline (already compact - just email + sign out), but the signed-out
 * form moves behind a dialog instead of living directly in the header.
 * The dialog title/description stays mode-agnostic ("Welcome", not
 * "Sign in") because AuthWidget owns its own sign-in/sign-up toggle state
 * internally (Part 3.6) - a static "Sign in to Aspirova" title would
 * contradict itself once the user switches to the sign-up view.
 */
export default function HeaderAuth() {
  const session = useSession();

  if (session) {
    return <AuthWidget />;
  }

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm">Sign in</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Welcome to Aspirova</DialogTitle>
          <DialogDescription>
            Sign in or create an account to track opportunities and get
            alerts on the companies you care about.
          </DialogDescription>
        </DialogHeader>
        <AuthWidget />
      </DialogContent>
    </Dialog>
  );
}
