"use client";

import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
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
  { href: "/", label: "All opportunities" },
  { href: "/jobs", label: "Jobs" },
  { href: "/internships", label: "Internships" },
  { href: "/remote", label: "Remote" },
  { href: "/competitions", label: "Competitions" },
  { href: "/scholarships", label: "Scholarships" },
  { href: "/research", label: "Research" },
  { href: "/programmes", label: "Programmes" },
  { href: "/companies", label: "Companies" },
  { href: "/pricing", label: "Pricing" },
] as const;

const PERSONAL_LINKS = [
  { href: "/saved", label: "Saved" },
  { href: "/resume", label: "Matches" },
  { href: "/referral", label: "Invite" },
] as const;

const MOBILE_NAV_LINK_CLASSES =
  "flex min-h-12 items-center rounded-md px-4 py-3 text-base font-medium text-foreground transition-colors duration-200 ease-premium hover:bg-secondary/50 aria-[current=page]:bg-accent aria-[current=page]:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:bg-secondary/70";

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  function isActive(href: string) {
    return pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)) ||
      (href === "/programmes" && pathname.startsWith("/programme/")) ||
      (href === "/" && pathname.startsWith("/opportunity/"));
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="lg:hidden"
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
        <nav className="flex min-h-0 flex-col gap-1 overflow-y-auto px-4 pb-4" aria-label="Mobile navigation">
          {NAV_LINKS.map((link) => (
            <HoverPrefetchLink
              key={link.href}
              href={link.href}
              className={MOBILE_NAV_LINK_CLASSES}
              aria-current={isActive(link.href) ? "page" : undefined}
              onClick={() => setOpen(false)}
            >
              {link.label}
            </HoverPrefetchLink>
          ))}
          <div className="mt-3 flex flex-col gap-1 border-t border-border pt-3">
            {PERSONAL_LINKS.map((link) => (
              <HoverPrefetchLink
                key={link.href}
                href={link.href}
                className={MOBILE_NAV_LINK_CLASSES}
                aria-current={isActive(link.href) ? "page" : undefined}
                onClick={() => setOpen(false)}
              >
                {link.label}
              </HoverPrefetchLink>
            ))}
          </div>
        </nav>
      </SheetContent>
    </Sheet>
  );
}
