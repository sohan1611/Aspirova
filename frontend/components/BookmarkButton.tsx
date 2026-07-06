"use client";

import { Bookmark, BookmarkCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { addBookmark, getBookmarks, removeBookmark } from "@/lib/api";
import { useSession } from "@/lib/useSession";

export default function BookmarkButton({ slug }: { slug: string }) {
  const session = useSession();
  const [bookmarked, setBookmarked] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!session) return;
    getBookmarks(session.access_token)
      .then((items) => setBookmarked(items.some((item) => item.slug === slug)))
      .catch(() => {});
  }, [session, slug]);

  if (!session) {
    return <span className="text-sm text-muted-foreground">Sign in to bookmark</span>;
  }

  async function toggle() {
    if (!session) return;
    setLoading(true);
    try {
      if (bookmarked) {
        await removeBookmark(slug, session.access_token);
        setBookmarked(false);
      } else {
        await addBookmark(slug, session.access_token);
        setBookmarked(true);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button
      variant={bookmarked ? "secondary" : "outline"}
      onClick={toggle}
      disabled={loading}
      aria-pressed={bookmarked}
    >
      {bookmarked ? <BookmarkCheck /> : <Bookmark />}
      {bookmarked ? "Bookmarked" : "Bookmark"}
    </Button>
  );
}
