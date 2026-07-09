import { cn } from "@/lib/utils";

interface AccountAvatarProps {
  email: string | null | undefined;
  avatarUrl?: string | null;
  className?: string;
}

export default function AccountAvatar({
  email,
  avatarUrl,
  className,
}: AccountAvatarProps) {
  const initial = email?.trim().charAt(0).toUpperCase() || "A";

  if (avatarUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- OAuth avatar URLs are remote and provider domains are not fixed.
      <img
        src={avatarUrl}
        alt=""
        referrerPolicy="no-referrer"
        className={cn(
          "size-10 shrink-0 rounded-full object-cover ring-1 ring-border",
          className,
        )}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-primary font-serif text-base font-semibold text-primary-foreground ring-1 ring-primary/20",
        className,
      )}
    >
      {initial}
    </span>
  );
}
