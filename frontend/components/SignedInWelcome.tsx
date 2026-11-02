"use client";

import Link from "next/link";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

const QUICK_LINKS = [
  { href: "/saved", label: "Saved" },
  { href: "/resume", label: "Matches" },
  { href: "/competitions", label: "Competitions" },
] as const;

export default function SignedInWelcome() {
  const session = useSession();

  return (
    <section
      aria-label="Member welcome"
      className={cn("border-b border-border py-5 sm:py-6", !session && "auth-show-while-pending")}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="eyebrow text-heritage">Your almanac</p>
          <p className="mt-1.5 text-sm font-medium text-foreground">
            Welcome back. Pick up where you left off.
          </p>
        </div>

        <nav aria-label="Your shortcuts" className="flex flex-wrap items-center gap-2">
          {QUICK_LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}
