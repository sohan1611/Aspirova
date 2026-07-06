import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function OpportunityNotFound() {
  return (
    <main className="mx-auto max-w-prose px-4 py-16 text-center">
      <h1 className="text-xl font-semibold text-foreground">Opportunity not found</h1>
      <p className="mt-2 text-muted-foreground">
        This listing may have expired or the link is incorrect.
      </p>
      <Button variant="outline" className="mt-4" asChild>
        <Link href="/">← Back to feed</Link>
      </Button>
    </main>
  );
}
