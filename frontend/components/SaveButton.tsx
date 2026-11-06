"use client";

import { Bookmark, BookmarkCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBookmarks } from "@/components/BookmarksProvider";
import { cn } from "@/lib/utils";

interface SaveButtonProps {
  slug: string;
  title?: string;
  className?: string;
}

export default function SaveButton({ slug, title, className }: SaveButtonProps) {
  const { ready, signedIn, isSaved, toggle } = useBookmarks();
  const saved = isSaved(slug);
  const opportunityLabel = title ?? "this opportunity";

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className={cn(
        "bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-primary focus-visible:bg-secondary focus-visible:text-primary",
        saved && "text-primary",
        className,
      )}
      aria-pressed={saved}
      aria-label={saved ? `Saved: ${opportunityLabel}` : `Save ${opportunityLabel}`}
      aria-disabled={signedIn && !ready}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void toggle(slug);
      }}
    >
      {saved ? (
        <BookmarkCheck className="fill-primary/20" aria-hidden="true" />
      ) : (
        <Bookmark aria-hidden="true" />
      )}
    </Button>
  );
}
