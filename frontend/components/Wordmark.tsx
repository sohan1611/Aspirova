import Link from "next/link";
import { cn } from "@/lib/utils";

type WordmarkProps = {
  className?: string;
};

export function Wordmark({ className }: WordmarkProps) {
  return (
    <Link
      href="/"
      className={cn(
        "inline-flex items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- tiny static brand mark; next/image is overkill here */}
      <img
        src="/logo.png"
        alt="Aspirova"
        width={28}
        height={28}
        className="h-7 w-7 shrink-0 rounded-full ring-1 ring-border"
      />
      <span className="font-serif text-lg font-semibold tracking-tight text-foreground">
        Aspirova
      </span>
    </Link>
  );
}

export default Wordmark;
