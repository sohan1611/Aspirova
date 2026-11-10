"use client";

import { CircleCheck } from "lucide-react";
import Link from "next/link";
import { useBookmarks } from "@/components/BookmarksProvider";
import { trackerStageMessage } from "@/lib/trackerStage";

export default function TrackerStageNotice({ slug }: { slug: string }) {
  const { signedIn, statusesReady, status } = useBookmarks();
  if (!signedIn || !statusesReady) return null;

  const message = trackerStageMessage(status(slug));
  if (!message) return null;

  return (
    <p className="mb-3 flex min-w-0 items-start gap-2 text-sm leading-6 text-muted-foreground">
      <CircleCheck className="mt-1 size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 break-words">
        {message}{" "}
        <Link href="/saved" className="underline underline-offset-4 hover:text-primary">
          View in your tracker
        </Link>
      </span>
    </p>
  );
}
