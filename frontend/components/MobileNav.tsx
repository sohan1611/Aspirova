"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

const NAV_LINKS = [
  { href: "/saved", label: "Saved" },
  { href: "/resume", label: "Matches" },
  { href: "/referral", label: "Invite" },
  { href: "/copilot", label: "Copilot" },
  { href: "/competitions", label: "Competitions" },
  { href: "/research", label: "Research" },
  // Scholarships is deliberately NOT linked here yet. The route, its ISR
  // wiring and the crawl are all live, but Unstop only had 3 open
  // scholarships on 2026-09-01 (the 2,383 figure was an all-time archive
  // count - the adapter sends oppstatus=open). Restore this link when the
  // page carries enough to be worth a nav slot.
  { href: "/programmes", label: "Programmes" },
  { href: "/pricing", label: "Pricing" },
] as const;

const MOBILE_NAV_LINK_CLASSES =
  "flex min-h-12 items-center rounded-md px-4 py-3 text-base font-medium text-foreground transition-colors duration-200 ease-premium hover:bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:bg-secondary/70";

export default function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open menu"
        >
          <Menu className="size-5" aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left">
        <SheetHeader className="border-b border-border">
          <SheetTitle className="font-serif text-xl">Menu</SheetTitle>
          <SheetDescription className="sr-only">
            Navigate to another section of Aspirova.
          </SheetDescription>
        </SheetHeader>
        <nav className="flex flex-col gap-1 px-4" aria-label="Mobile navigation">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={MOBILE_NAV_LINK_CLASSES}
              onClick={() => setOpen(false)}
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
