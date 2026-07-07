import Link from "next/link";
import HeaderAuth from "@/components/HeaderAuth";
import ThemeToggle from "@/components/ThemeToggle";
import Wordmark from "@/components/Wordmark";

export default function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-4xl items-center justify-between gap-2 px-3 sm:gap-4 sm:px-4">
        <div className="flex items-center gap-3 sm:gap-6">
          <Wordmark className="[&>span]:hidden sm:[&>span]:inline" />
          <nav className="flex items-center gap-3 text-sm font-medium sm:gap-4">
            <Link
              href="/resume"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Matches
            </Link>
            <Link
              href="/referral"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Invite
            </Link>
            <Link
              href="/copilot"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Copilot
            </Link>
            <Link
              href="/pricing"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Pricing
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <HeaderAuth />
        </div>
      </div>
    </header>
  );
}
