"use client";

import { Bookmark, BookmarkCheck } from "lucide-react";
import { useBookmarks } from "@/components/BookmarksProvider";
import { Button } from "@/components/ui/button";

export default function BookmarkButton({ slug }: { slug: string }) {
  const { ready, signedIn, isSaved, toggle } = useBookmarks();
  const saved = isSaved(slug);

  if (!signedIn) {
    return <span className="text-sm text-muted-foreground">Sign in to save</span>;
  }

  return (
    <Button
      variant={saved ? "secondary" : "outline"}
      onClick={() => void toggle(slug)}
      disabled={!ready}
      aria-pressed={saved}
    >
      {saved ? <BookmarkCheck /> : <Bookmark />}
      {saved ? "Saved" : "Save"}
    </Button>
  );
}
