"use client";

import { useEffect, useState, type ComponentProps } from "react";
import { toast } from "sonner";
import AuthWidget from "@/components/AuthWidget";
import { useBookmarks } from "@/components/BookmarksProvider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { pingOpportunityAction } from "@/lib/api";
import { isAuthPending } from "@/lib/authPending";
import { useSessionState } from "@/lib/useSession";

const PENDING_APPLY_KEY = "aspirova:pending-apply";
const DAY_MS = 24 * 60 * 60 * 1000;

interface ApplyLinkProps {
  slug: string;
  href: string;
  children: React.ReactNode;
  size?: ComponentProps<typeof Button>["size"];
  variant?: ComponentProps<typeof Button>["variant"];
  className?: string;
}

export default function ApplyLink({ slug, href, children, size, variant, className }: ApplyLinkProps) {
  const { session, resolved } = useSessionState();
  const { ready, statusesReady, status, markApplied } = useBookmarks();
  const [open, setOpen] = useState(false);
  const [promptSlug, setPromptSlug] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const bookmarkStatus = status(slug);
  const progressed =
    bookmarkStatus !== undefined &&
    ["applied", "interviewing", "offer"].includes(bookmarkStatus);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    function checkPendingApply() {
      clearTimeout(timer);
      if (!session || document.visibilityState !== "visible") return;
      try {
        const entry = JSON.parse(localStorage.getItem(PENDING_APPLY_KEY) ?? "null");
        const age = typeof entry?.at === "number" ? Date.now() - entry.at : NaN;
        const matches = entry?.slug === slug && Number.isFinite(age);
        setPromptSlug(matches && age >= 10_000 && age <= DAY_MS ? slug : null);
        if (matches && age >= 0 && age < 10_000) {
          timer = setTimeout(checkPendingApply, 10_000 - age);
        } else if (matches && age >= 10_000 && age <= DAY_MS) {
          timer = setTimeout(checkPendingApply, DAY_MS - age + 1);
        }
        if (entry?.slug === slug && age > DAY_MS) localStorage.removeItem(PENDING_APPLY_KEY);
      } catch {
        setPromptSlug(null);
      }
    }
    timer = setTimeout(checkPendingApply, 0);
    document.addEventListener("visibilitychange", checkPendingApply);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", checkPendingApply);
    };
  }, [session, slug]);

  function clearPendingApply() {
    try {
      const entry = JSON.parse(localStorage.getItem(PENDING_APPLY_KEY) ?? "null");
      if (entry?.slug === slug) localStorage.removeItem(PENDING_APPLY_KEY);
    } catch {
      // Storage can be unavailable in private browsing.
    }
    setPromptSlug(null);
  }

  function shouldGate() {
    if (session) return false;
    // Session still settling for someone who is probably signed in: never block them.
    if (!resolved && isAuthPending()) return false;
    return true;
  }

  function recordApply() {
    void pingOpportunityAction(slug, "apply");
    if (!session) return;
    setPromptSlug(null);
    try {
      localStorage.setItem(PENDING_APPLY_KEY, JSON.stringify({ slug, at: Date.now() }));
    } catch {
      // Applying still works when storage is unavailable.
    }
  }

  function handleClick(event: React.MouseEvent<HTMLAnchorElement>) {
    if (shouldGate()) {
      event.preventDefault();
      void pingOpportunityAction(slug, "gate");
      setOpen(true);
    } else {
      recordApply();
    }
  }

  async function confirmApplied() {
    if (saving || !ready || progressed) return;
    setSaving(true);
    try {
      await markApplied(slug);
      clearPendingApply();
      toast.success("Marked as applied", {
        action: {
          label: "View saved",
          onClick: () => { window.location.href = "/saved"; },
        },
      });
    } catch {
      toast.error("Couldn't mark this as applied. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {/* Keep Doc 04's real source link while gating clicks; Google's policy requires public job details. */}
      <Button size={size} variant={variant} className={className} asChild>
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          onAuxClick={(event) => {
            if (event.button === 1) handleClick(event);
          }}
        >
          {children}
        </a>
      </Button>
      {session && statusesReady && promptSlug === slug && !progressed && (
        <div className="mt-3 basis-full rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Did you apply?</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" size="sm" disabled={saving} onClick={() => void confirmApplied()}>
              {saving ? "Saving…" : "Yes, I applied"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={saving}
              onClick={clearPendingApply}
            >
              Not yet
            </Button>
          </div>
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{session ? "You're signed in" : "Sign in to apply"}</DialogTitle>
            <DialogDescription>
              {session
                ? "Continue to the original listing to apply."
                : "It's free and takes a few seconds. We'll bring you straight back to this job."}
            </DialogDescription>
          </DialogHeader>
          {session ? (
            <Button asChild>
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => {
                  recordApply();
                  setOpen(false);
                }}
                onAuxClick={(event) => {
                  if (event.button === 1) {
                    recordApply();
                    setOpen(false);
                  }
                }}
              >
                {children}
              </a>
            </Button>
          ) : (
            <AuthWidget />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
