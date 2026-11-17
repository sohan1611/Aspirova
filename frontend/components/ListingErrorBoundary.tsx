"use client";
import { useRouter } from "next/navigation";
import { ListingFailure } from "@/components/ListingFeedback";
export default function ListingErrorBoundary({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const router = useRouter();
  return <main className="mx-auto max-w-6xl px-4 py-12"><h1 className="font-serif text-2xl font-bold">Results couldn&apos;t be loaded</h1><ListingFailure retry={() => { router.refresh(); reset(); }} /></main>;
}
