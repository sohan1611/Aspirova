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
 * AuthWidget's own internal presentation (labels, inline validation,
 * loading/error/success states) is intentionally untouched here - that
 * redesign is Part 3.6's job.
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
          <DialogTitle>Sign in to Aspirova</DialogTitle>
          <DialogDescription>
            Track opportunities and get alerts on the companies you care about.
          </DialogDescription>
        </DialogHeader>
        <AuthWidget />
      </DialogContent>
    </Dialog>
  );
}
