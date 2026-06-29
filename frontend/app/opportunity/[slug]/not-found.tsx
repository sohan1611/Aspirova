import Link from "next/link";

export default function OpportunityNotFound() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16 text-center">
      <h1 className="text-xl font-semibold">Opportunity not found</h1>
      <p className="mt-2 text-gray-500">
        This listing may have expired or the link is incorrect.
      </p>
      <Link href="/" className="mt-4 inline-block underline">
        ← Back to feed
      </Link>
    </main>
  );
}
