import { Search } from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import HeaderAuth from "@/components/HeaderAuth";
import HeaderNav from "@/components/HeaderNav";
import MobileNav from "@/components/MobileNav";
import NotificationBell from "@/components/NotificationBell";
import Wordmark from "@/components/Wordmark";
import { Button } from "@/components/ui/button";

export default function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-card">
      <div className="mx-auto flex h-16 max-w-[1680px] items-center justify-between gap-2 px-4 sm:gap-3 sm:px-6 lg:gap-2 lg:px-10 xl:px-12">
        <div className="flex min-w-0 shrink-0 items-center gap-1 md:gap-3">
          <Wordmark className="[&>span]:hidden md:[&>span]:inline lg:[&>span]:text-[22px]" />
          <MobileNav />
        </div>
        <HeaderNav />
        <div className="flex shrink-0 items-center gap-1 xl:gap-2">
          <Button variant="outline" asChild className="size-11 p-0 sm:size-9 lg:w-auto lg:px-3">
            <HoverPrefetchLink href="/#feed-search" aria-label="Search opportunities">
              <Search className="size-4" aria-hidden="true" />
              <span className="hidden lg:inline">Search</span>
            </HoverPrefetchLink>
          </Button>
          <Button variant="outline" asChild className="hidden px-3 md:inline-flex">
            <HoverPrefetchLink href="/pricing">Pricing</HoverPrefetchLink>
          </Button>
          <NotificationBell />
          <HeaderAuth triggerVariant="default" triggerClassName="px-3 xl:px-4" />
        </div>
      </div>
    </header>
  );
}