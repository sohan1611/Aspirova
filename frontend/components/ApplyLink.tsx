"use client";

import { useState, type ComponentProps } from "react";
import AuthWidget from "@/components/AuthWidget";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { isAuthPending } from "@/lib/authPending";
import { useSessionState } from "@/lib/useSession";

interface ApplyLinkProps {
  href: string;
  children: React.ReactNode;
  size?: ComponentProps<typeof Button>["size"];
  variant?: ComponentProps<typeof Button>["variant"];
}

export default function ApplyLink({ href, children, size, variant }: ApplyLinkProps) {
  const { session, resolved } = useSessionState();
  const [open, setOpen] = useState(false);

  const shouldGate = () => {
    if (session) return false;
    // Session still settling for someone who is probably signed in: never block them.
    if (!resolved && isAuthPending()) return false;
    return true;
  };

  return (
    <>
      {/* Keep Doc 04's real source link while gating clicks; Google's policy requires public job details. */}
      <Button size={size} variant={variant} asChild>
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => {
            if (shouldGate()) {
              event.preventDefault();
              setOpen(true);
            }
          }}
          onAuxClick={(event) => {
            if (event.button === 1 && shouldGate()) {
              event.preventDefault();
              setOpen(true);
            }
          }}
        >
          {children}
        </a>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{session ? "You're signed in" : "Sign in to apply"}</DialogTitle>
            <DialogDescription>
              {session
                ? "Continue to the company's site to apply."
                : "It's free and takes a few seconds. We'll bring you straight back to this job."}
            </DialogDescription>
          </DialogHeader>
          {session ? (
            <>
              <Button asChild>
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setOpen(false)}
                >
                  {children}
                </a>
              </Button>
            </>
          ) : (
            <AuthWidget />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
