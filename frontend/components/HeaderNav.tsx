"use client";

import { ChevronDown } from "lucide-react";
import { usePathname } from "next/navigation";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const OPPORTUNITY_LINKS = [
  { href: "/", label: "All opportunities" },
  { href: "/jobs", label: "Jobs" },
  { href: "/internships", label: "Internships" },
  { href: "/remote", label: "Remote" },
  { href: "/scholarships", label: "Scholarships" },
  { href: "/companies", label: "Companies" },
];
const NAV_LINKS = [
  { href: "/competitions", label: "Competitions" },
  { href: "/research", label: "Research" },
  { href: "/programmes", label: "Programmes" },
  { href: "/calendar", label: "Hiring Calendar" },
  { href: "/saved", label: "Saved" },
  { href: "/resume", label: "Matches" },
];
const NAV_CLASS = "relative inline-flex h-16 shrink-0 items-center gap-1 whitespace-nowrap font-serif text-[14px] xl:text-[15px] font-semibold text-foreground/75 transition-colors hover:text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-transparent";
const ACTIVE_CLASS = "text-primary after:bg-primary";

export default function HeaderNav() {
  const pathname = usePathname();
  const opportunitiesActive =
    pathname === "/" || pathname.startsWith("/opportunity/") ||
    OPPORTUNITY_LINKS.some(({ href }) => href !== "/" && (pathname === href || pathname.startsWith(`${href}/`)));
  return (
    <nav aria-label="Main navigation" className="hidden min-w-0 items-center gap-5 xl:flex">
      <DropdownMenu>
        <DropdownMenuTrigger
          className={cn(NAV_CLASS, opportunitiesActive && ACTIVE_CLASS)}
          aria-current={opportunitiesActive ? "page" : undefined}
        >
          Opportunities <ChevronDown className="size-3" aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {OPPORTUNITY_LINKS.map(({ href, label }) => (
            <DropdownMenuItem key={href} asChild>
              <HoverPrefetchLink href={href} aria-current={pathname === href ? "page" : undefined}>
                {label}
              </HoverPrefetchLink>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      {NAV_LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`) ||
          (href === "/programmes" && pathname.startsWith("/programme/"));
        return (
          <HoverPrefetchLink
            key={href}
            href={href}
            className={cn(NAV_CLASS, active && ACTIVE_CLASS)}
            aria-current={active ? "page" : undefined}
          >
            {label}
          </HoverPrefetchLink>
        );
      })}
    </nav>
  );
}
