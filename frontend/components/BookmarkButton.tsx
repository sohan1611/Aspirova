"use client";

import { useEffect, useState } from "react";
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
    return <span className="text-sm text-gray-500">Sign in to bookmark</span>;
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
    <button
      onClick={toggle}
      disabled={loading}
      className={`rounded border px-3 py-2 text-sm transition-colors ${
        bookmarked ? "bg-black text-white" : "hover:bg-gray-100"
      }`}
    >
      {bookmarked ? "Bookmarked ✓" : "Bookmark"}
    </button>
  );
}
