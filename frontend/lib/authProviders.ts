import type { User } from "@supabase/supabase-js";

export function providersFor(user: User | null | undefined): string[] {
  const identityProviders = Array.isArray(user?.identities)
    ? user.identities
        .map((identity) => identity?.provider)
        .filter((provider): provider is string => typeof provider === "string")
    : [];
  const metadataProviders: unknown = user?.app_metadata?.providers;
  const fallbackProviders = Array.isArray(metadataProviders)
    ? metadataProviders.filter(
        (provider): provider is string => typeof provider === "string",
      )
    : [];
  const primaryProvider: unknown = user?.app_metadata?.provider;

  return Array.from(
    new Set([
      ...identityProviders,
      ...fallbackProviders,
      ...(typeof primaryProvider === "string" ? [primaryProvider] : []),
    ]),
  );
}

export function providerLabel(provider: string): string {
  if (provider === "github") return "GitHub";
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

