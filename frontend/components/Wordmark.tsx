import Link from "next/link";

/**
 * Minimal geometric mark (no image asset/pipeline needed) - a compass-like
 * arrow standing in for "discovery," paired with the wordmark. Uses
 * currentColor so it's automatically theme-aware.
 */
export default function Wordmark({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      className={`inline-flex items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${className ?? ""}`}
    >
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-6 w-6 shrink-0 text-primary"
      >
        <rect width="24" height="24" rx="6" fill="currentColor" />
        <path
          d="M7 15.5L12 8l5 7.5"
          stroke="var(--color-primary-foreground)"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
        <circle cx="12" cy="8" r="1.4" fill="var(--color-primary-foreground)" />
      </svg>
      <span className="text-lg font-bold tracking-tight text-foreground">Aspirova</span>
    </Link>
  );
}
