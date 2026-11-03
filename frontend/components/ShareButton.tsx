"use client";

import { MessageCircle, Share2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { getReferralMe } from "@/lib/api";
import { useHydrated } from "@/lib/useHydrated";
import { useSession } from "@/lib/useSession";

interface ShareButtonProps {
  slug: string;
  title: string;
}

interface CachedInviteCode {
  accessToken: string;
  inviteCode: string;
}

export default function ShareButton({ slug, title }: ShareButtonProps) {
  const session = useSession();
  const hydrated = useHydrated();
  const fallbackInputRef = useRef<HTMLInputElement>(null);
  const cachedInviteCodeRef = useRef<CachedInviteCode | null>(null);
  const [loading, setLoading] = useState(false);

  const origin = hydrated && typeof window !== "undefined" ? window.location.origin : "";
  const baseUrl = origin
    ? `${origin}/opportunity/${encodeURIComponent(slug)}`
    : `/opportunity/${encodeURIComponent(slug)}`;

  function whatsappUrl(link: string): string {
    const url = new URL(link, "https://www.aspirova.org");
    url.searchParams.set("utm_source", "whatsapp");
    return `https://wa.me/?text=${encodeURIComponent(`${title} ${url.toString()}`)}`;
  }

  async function copyLink(link: string): Promise<"copied" | "selected"> {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(link);
        return "copied";
      }
    } catch {
      // Fall through to the selected URL fallback.
    }

    const input = fallbackInputRef.current;
    if (input) {
      input.value = link;
      input.focus();
      input.select();
      input.setSelectionRange(0, link.length);
    }

    try {
      if (document.execCommand("copy")) {
        return "copied";
      }
    } catch {
      // Selecting the text is enough when programmatic copy is unavailable.
    }

    return "selected";
  }

  async function getInviteCode(accessToken: string): Promise<string | null> {
    const cached = cachedInviteCodeRef.current;
    if (cached?.accessToken === accessToken) {
      return cached.inviteCode;
    }

    try {
      const referral = await getReferralMe(accessToken);
      cachedInviteCodeRef.current = {
        accessToken,
        inviteCode: referral.invite_code,
      };
      return referral.invite_code;
    } catch {
      return null;
    }
  }

  async function handleShare() {
    setLoading(true);
    try {
      const accessToken = session?.access_token;
      const inviteCode = accessToken ? await getInviteCode(accessToken) : null;
      const link = inviteCode ? `${baseUrl}?ref=${encodeURIComponent(inviteCode)}` : baseUrl;
      if (navigator.share) {
        try {
          await navigator.share({ title, url: link });
          return;
        } catch (error) {
          if (error instanceof Error && error.name === "AbortError") return;
        }
      }
      const result = await copyLink(link);

      if (result === "copied") {
        toast.success("Link copied — share it to invite friends");
      } else {
        toast("Link selected");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleWhatsApp() {
    const popup = window.open("", "_blank");
    if (popup) popup.opener = null;
    setLoading(true);
    try {
      const accessToken = session?.access_token;
      const inviteCode = accessToken ? await getInviteCode(accessToken) : null;
      const link = inviteCode ? `${baseUrl}?ref=${encodeURIComponent(inviteCode)}` : baseUrl;
      const href = whatsappUrl(link);
      if (popup && !popup.closed) {
        popup.location.href = href;
      } else {
        window.location.href = href;
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Button
        variant="outline"
        onClick={handleShare}
        disabled={loading}
        aria-label="Share this opportunity"
      >
        <Share2 aria-hidden="true" />
        Share
      </Button>
      {session ? (
        <Button variant="outline" onClick={handleWhatsApp} disabled={loading}>
          <MessageCircle aria-hidden="true" />
          WhatsApp
        </Button>
      ) : (
        <Button variant="outline" asChild>
          <a href={whatsappUrl(baseUrl)} target="_blank" rel="noopener noreferrer">
            <MessageCircle aria-hidden="true" />
            WhatsApp
          </a>
        </Button>
      )}
      <input
        ref={fallbackInputRef}
        aria-hidden="true"
        className="sr-only"
        readOnly
        tabIndex={-1}
      />
    </>
  );
}
