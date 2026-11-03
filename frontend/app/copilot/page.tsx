import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Career Copilot isn't available yet",
  description: "Career Copilot is paused. The feed and resume check are free to use.",
  robots: { index: false },
};

export default function CopilotPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-16 sm:px-8 sm:py-20">
      <h1 className="font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
        Career Copilot isn&apos;t available yet
      </h1>
      <p className="mt-5 text-lg leading-8 text-muted-foreground">
        We&apos;ve paused it for now. In the meantime, the feed and the resume check are free to use.
      </p>
      <div className="mt-8 flex flex-wrap gap-6 text-sm font-medium">
        <Link href="/" className="underline underline-offset-4">Browse the feed</Link>
        <Link href="/resume" className="underline underline-offset-4">Resume check</Link>
      </div>
    </main>
  );
}
