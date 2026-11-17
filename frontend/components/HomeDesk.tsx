"use client";

import { Component, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import ActionSource from "@/components/ActionSource";
import ListingFreshness from "@/components/ListingFreshness";
import { actionDateLabel, stageLabel } from "@/lib/actionCenter";
import { getHomeDesk } from "@/lib/api";
import { formatDateUtc } from "@/lib/date";
import { DESK_BLOCKS, validDeskBlock, type DeskBlock, type DeskDeadline, type DeskKey, type HomeDesk } from "@/lib/home";
import type { OpportunityListItem, SavedOpportunityItem } from "@/lib/types";
import { useSessionState } from "@/lib/useSession";

const linkClass = "inline-flex min-h-11 items-center rounded text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const blocks: Record<DeskKey, { title: string; empty: string; href: string; action: string }> = {
  matches: { title: "New matches", empty: "Set interests or add skills to find relevant new roles.", href: "/account?section=profile", action: "Set interests" },
  deadlines: { title: "Next deadlines", empty: "Save listings or watch programmes to track explicit deadlines here.", href: "/calendar", action: "Open the calendar" },
  followed: { title: "Companies you follow", empty: "No recent roles from your follows. Follow a company to watch for updates.", href: "/companies", action: "Follow a company" },
  applications: { title: "Unfinished applications", empty: "Save a listing and move it to Planned to start tracking your next step.", href: "/#feed-search", action: "Find a listing to save" },
  warnings: { title: "Verification warnings", empty: "No closure or safety warnings on your tracked listings. Check saved targets before applying.", href: "/saved", action: "Review saved listings" },
};

function FailedBlock({ blockKey, retry }: { blockKey: DeskKey; retry: () => void }) {
  return <div className="text-sm text-muted-foreground">
    <p>Couldn&apos;t load {blocks[blockKey].title.toLowerCase()}.</p>
    <button type="button" onClick={retry} className={linkClass}>Try again</button>
    <p><Link href={blocks[blockKey].href} className={linkClass}>{blocks[blockKey].action}</Link></p>
  </div>;
}

class BlockBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function RoleRow({ item }: { item: OpportunityListItem }) {
  const date = item.posted_at || item.last_seen_at;
  return <>
    <Link href={`/opportunity/${item.slug}`} className={`${linkClass} break-words`}>{item.title}</Link>
    <p className="text-xs text-muted-foreground">{item.company?.name}</p>
    <ListingFreshness postedAt={item.posted_at} lastSeenAt={item.last_seen_at} absoluteText={formatDateUtc(date)} />
  </>;
}

function BlockItems({ blockKey, block }: { blockKey: DeskKey; block: DeskBlock<unknown> }) {
  if (block.items.length === 0) return <p className="text-sm leading-6 text-muted-foreground">
    {blockKey === "matches" && block.reason === "no_new_matches"
      ? "No new matches in the last 14 days. Adjust your interests or explore the full feed below."
      : blocks[blockKey].empty}
  </p>;
  return <ol className="divide-y divide-border">
    {block.items.map((value, index) => {
      if (blockKey === "deadlines") {
        const item = value as DeskDeadline;
        return <li key={`${item.kind}-${item.slug}-${index}`} className="py-2 first:pt-0">
          <Link href={item.kind === "listing" ? `/opportunity/${item.slug}` : `/calendar?q=${encodeURIComponent(item.title)}`} className={linkClass}>{item.title}</Link>
          <p className="text-xs text-muted-foreground">Explicit deadline · <time dateTime={item.deadline}>{formatDateUtc(item.deadline)}</time></p>
        </li>;
      }
      const item = value as OpportunityListItem;
      const saved = value as SavedOpportunityItem;
      return <li key={item.slug} className="py-2 first:pt-0">
        <RoleRow item={item} />
        {blockKey === "applications" && <p className="mt-1 text-xs text-muted-foreground">{stageLabel(saved.bookmark_status)}{actionDateLabel(saved) ? ` · ${actionDateLabel(saved)}` : " · Add a date or note in Saved"}</p>}
        {(blockKey === "applications" || blockKey === "warnings") && <div className="mt-2"><ActionSource item={saved} /></div>}
      </li>;
    })}
  </ol>;
}

export function HomeDeskView({ data, loading, error, retry }: {
  data: Partial<HomeDesk> | null; loading: boolean; error: boolean; retry: () => void;
}) {
  return <>
    <div className="flex flex-wrap items-center justify-between gap-x-4">
      <div>
        <p className="eyebrow text-primary">Your almanac</p>
        <h1 id="home-desk-title" className="mt-2 font-serif text-3xl font-bold">Your action desk</h1>
      </div>
      <Link href="#feed-search" className={linkClass}>Browse the full feed ↓</Link>
    </div>
    <p className="mt-2 text-sm text-muted-foreground">New roles discovered in the last 14 days, ranked by your saved interests and skills. Dates and sources need your final check.</p>
    <p role="status" className="sr-only">{loading ? "Loading your action desk" : error ? "Action desk unavailable. The full feed is below." : "Action desk updated"}</p>
    <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {DESK_BLOCKS.map(blockKey => {
        const block = data?.[blockKey];
        const valid = validDeskBlock(block);
        return <section key={blockKey} aria-labelledby={`desk-${blockKey}`} aria-busy={loading} className="flex h-80 min-w-0 flex-col rounded-lg border border-border bg-card p-4">
          <h2 id={`desk-${blockKey}`} className="font-serif text-xl font-bold">{blocks[blockKey].title}{valid && !loading ? ` (${block.count})` : ""}</h2>
          <div className="mt-2 min-h-0 flex-1 overflow-y-auto [overflow-wrap:anywhere]">
            {loading ? <div aria-hidden="true" className="animate-pulse space-y-4 pt-2"><div className="h-5 w-4/5 rounded bg-muted" /><div className="h-4 w-1/2 rounded bg-muted" /><div className="h-5 w-3/4 rounded bg-muted" /></div>
              : error || !valid ? <FailedBlock blockKey={blockKey} retry={retry} />
              : <BlockBoundary key={JSON.stringify(block)} fallback={<FailedBlock blockKey={blockKey} retry={retry} />}><BlockItems blockKey={blockKey} block={block} /></BlockBoundary>}
          </div>
          <Link href={blocks[blockKey].href} className={`${linkClass} mt-2 shrink-0`}>{blocks[blockKey].action}</Link>
        </section>;
      })}
    </div>
  </>;
}

export default function HomeActionDesk() {
  const { session, resolved } = useSessionState();
  const token = session?.access_token;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ token?: string; attempt: number; data: HomeDesk | null; error: boolean }>({ attempt: -1, data: null, error: false });
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    getHomeDesk(token, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ token, attempt, data, error: false });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ token, attempt, data: null, error: true });
    });
    return () => controller.abort();
  }, [token, attempt]);

  if (resolved && !session) return null;
  const current = Boolean(token) && state.token === token && state.attempt === attempt;
  return <section aria-labelledby="home-desk-title" className={`border-b border-border py-5 sm:py-8${!session ? " auth-show-while-pending" : ""}`}>
    <HomeDeskView data={current ? state.data : null} loading={!current} error={current && state.error} retry={() => setAttempt(value => value + 1)} />
  </section>;
}
