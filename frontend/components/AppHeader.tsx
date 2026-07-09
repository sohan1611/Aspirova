import Link from "next/link";
import HeaderAuth from "@/components/HeaderAuth";
import Wordmark from "@/components/Wordmark";

const NAV_LINK_CLASSES =
  "relative py-1 text-muted-foreground transition-colors duration-300 ease-premium after:absolute after:inset-x-0 after:bottom-0 after:h-px after:origin-left after:scale-x-0 after:bg-primary after:transition-transform after:duration-300 after:ease-premium hover:text-foreground hover:after:scale-x-100 focus-visible:text-foreground focus-visible:after:scale-x-100 active:text-foreground";

export default function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1680px] items-center justify-between gap-2 px-4 sm:gap-4 sm:px-6 lg:px-10 xl:px-12">
        <div className="flex items-center gap-3 sm:gap-6">
          <Wordmark className="[&>span]:hidden [&>span]:tracking-[-0.01em] sm:[&>span]:inline" />
          <nav className="flex items-center gap-3 text-sm font-medium sm:gap-4">
            <Link href="/resume" className={NAV_LINK_CLASSES}>
              Matches
            </Link>
            <Link href="/referral" className={NAV_LINK_CLASSES}>
              Invite
            </Link>
            <Link href="/copilot" className={NAV_LINK_CLASSES}>
              Copilot
            </Link>
            <Link href="/pricing" className={NAV_LINK_CLASSES}>
              Pricing
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <HeaderAuth />
        </div>
      </div>
    </header>
  );
}
