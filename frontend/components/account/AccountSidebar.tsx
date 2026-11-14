"use client";

import { Bell, Bookmark, CreditCard, FileText, Shield, UserRound, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export const ACCOUNT_SECTIONS = [
  { key: "profile", label: "Profile", Icon: UserRound, group: "You" },
  { key: "resume", label: "Resume", Icon: FileText, group: "You" },
  { key: "notifications", label: "Notifications", Icon: Bell, group: "Alerts" },
  { key: "saved", label: "Saved searches", Icon: Bookmark, group: "Alerts" },
  { key: "subscription", label: "Subscription", Icon: CreditCard, group: "Account" },
  { key: "security", label: "Security", Icon: Shield, group: "Account" },
] as const satisfies ReadonlyArray<{ key: string; label: string; Icon: LucideIcon; group: "You" | "Alerts" | "Account" }>;

export type AccountSectionKey = (typeof ACCOUNT_SECTIONS)[number]["key"];

export function isAccountSection(value: string | null): value is AccountSectionKey {
  return ACCOUNT_SECTIONS.some((section) => section.key === value);
}

export default function AccountSidebar({ activeSection, hints }: {
  activeSection: AccountSectionKey; hints: Partial<Record<AccountSectionKey, string>>;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const mobileRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLAnchorElement>(null);

  function hrefFor(key: AccountSectionKey) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", key);
    return `${pathname}?${params.toString()}`;
  }

  useEffect(() => {
    const container = mobileRef.current;
    const active = activeRef.current;
    if (!container || !active || !container.clientWidth) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const containerBounds = container.getBoundingClientRect();
    const activeBounds = active.getBoundingClientRect();
    const left = container.scrollLeft + activeBounds.left - containerBounds.left
      - (container.clientWidth - activeBounds.width) / 2;
    container.scrollTo({ left, behavior: reduced ? "auto" : "smooth" });
  }, [activeSection]);

  return (
    <>
      <nav aria-label="Account sections" className="sticky top-16 z-30 -mx-4 self-start border-b border-border bg-background/95 md:hidden">
        <div ref={mobileRef} className="edge-fade-x flex snap-x scroll-px-4 gap-2 overflow-x-auto px-4 py-2.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {ACCOUNT_SECTIONS.map(({ key, label, Icon }) => (
            <Link key={key} ref={activeSection === key ? activeRef : undefined} href={hrefFor(key)} replace scroll={false} aria-current={activeSection === key ? "page" : undefined}
              className={cn("inline-flex min-h-11 shrink-0 snap-start items-center gap-2 rounded-full px-4 text-sm font-medium outline-none transition-colors duration-200 ease-premium focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background", activeSection === key ? "bg-primary text-primary-foreground shadow-soft" : "bg-card text-muted-foreground ring-1 ring-border hover:text-foreground")}>
              <Icon className="size-4" aria-hidden="true" />{label}
            </Link>
          ))}
        </div>
      </nav>
      <aside className="hidden md:block">
        <nav aria-label="Account sections" className="sticky top-24">
          {(["You", "Alerts", "Account"] as const).map((group) => (
            <div key={group} className="mt-5 first:mt-0">
              <p className="eyebrow mb-1.5 px-3">{group}</p>
              <div className="grid gap-1">
                {ACCOUNT_SECTIONS.filter((section) => section.group === group).map(({ key, label, Icon }) => {
                  const active = activeSection === key;
                  return (
                    <Link key={key} href={hrefFor(key)} replace scroll={false} aria-current={active ? "page" : undefined}
                      className={cn("group relative flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm font-medium outline-none transition-colors duration-200 ease-premium focus-visible:ring-2 focus-visible:ring-ring", active ? "bg-card text-foreground shadow-soft ring-1 ring-border" : "text-muted-foreground hover:bg-card/70 hover:text-foreground")}>
                      {active && <span aria-hidden="true" className="absolute inset-y-3 left-0 w-[3px] rounded-full bg-primary" />}
                      <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors duration-200 ease-premium", active ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground group-hover:text-foreground")}><Icon className="size-4" aria-hidden="true" /></span>
                      <span>{label}</span>
                      {hints[key] && <span className="tnum ml-auto min-w-0 truncate text-xs text-muted-foreground" title={hints[key]}>{hints[key]}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
