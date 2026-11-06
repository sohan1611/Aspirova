"use client";

import { Bookmark, Compass, ScanSearch, Trophy, User } from "lucide-react";
import { usePathname } from "next/navigation";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/", label: "Explore", icon: Compass, routes: ["/jobs", "/internships", "/remote", "/scholarships", "/companies", "/opportunity"] },
  { href: "/competitions", label: "Arena", icon: Trophy, routes: ["/competitions"] },
  { href: "/saved", label: "Saved", icon: Bookmark, routes: ["/saved"] },
  { href: "/resume", label: "Matches", icon: ScanSearch, routes: ["/resume"] },
  { href: "/account", label: "Profile", icon: User, routes: ["/account", "/notifications"] },
];

export default function MobileTabBar() {
  const pathname = usePathname();
  return (
    <nav aria-label="Bottom navigation" className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden">
      <div className="mx-auto grid h-16 max-w-md grid-cols-5 items-center gap-1 px-3">
        {TABS.map(({ href, label, icon: Icon, routes }) => {
          const active = pathname === href || routes.some((route) => pathname === route || pathname.startsWith(`${route}/`));
          return (
            <HoverPrefetchLink
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-12 min-w-0 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5 text-[11px] font-medium transition-colors",
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              <Icon className="size-5" aria-hidden="true" />
              {label}
            </HoverPrefetchLink>
          );
        })}
      </div>
    </nav>
  );
}
