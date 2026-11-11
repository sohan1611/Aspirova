"use client";

import type { ReactNode } from "react";
import { useSession } from "@/lib/useSession";

export default function SignedOutHeroVisibility({ children }: { children: ReactNode }) {
  const session = useSession();
  return session ? null : children;
}
