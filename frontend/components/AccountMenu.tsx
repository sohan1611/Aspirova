"use client";

import type { User } from "@supabase/supabase-js";
import { LogOut, Settings } from "lucide-react";
import Link from "next/link";
import AccountAvatar from "@/components/account/AccountAvatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { createClient } from "@/lib/supabase/client";

function avatarUrlFor(user: User): string | null {
  const avatarUrl: unknown = user.user_metadata?.avatar_url;
  return typeof avatarUrl === "string" ? avatarUrl : null;
}

export default function AccountMenu({ user }: { user: User }) {
  const supabase = createClient();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="rounded-full outline-none transition-transform duration-200 ease-premium hover:scale-[1.03] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <AccountAvatar
            email={user.email}
            avatarUrl={avatarUrlFor(user)}
            className="size-9"
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <span className="block text-xs text-muted-foreground">Signed in as</span>
          <span className="block truncate font-medium text-foreground">
            {user.email ?? "Aspirova member"}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/account">
            <Settings aria-hidden="true" />
            Account
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void supabase.auth.signOut()}>
          <LogOut aria-hidden="true" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
