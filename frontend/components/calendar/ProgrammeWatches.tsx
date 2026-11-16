"use client";

import { Bell, BellRing, ChevronDown } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import AuthWidget from "@/components/AuthWidget";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { addProgrammeWatch, getProgrammeWatches, removeProgrammeWatch, WATCH_UPDATES_COPY } from "@/lib/programmeWatches";
import type { ProgrammeWatch } from "@/lib/programmeWatches";
import { useSessionState } from "@/lib/useSession";

interface WatchContext {
  ready: boolean;
  loading: boolean;
  signedIn: boolean;
  items: ProgrammeWatch[];
  error: string;
  pending: string | null;
  reload: () => void;
  toggle: (slug: string) => Promise<void>;
}

const WatchesContext = createContext<WatchContext | null>(null);

export function ProgrammeWatchesProvider({ children }: { children: React.ReactNode }) {
  const { session, resolved } = useSessionState();
  const token = session?.access_token ?? null;
  const [state, setState] = useState<{ token: string | null; items: ProgrammeWatch[]; error: string; loaded: boolean }>({ token: null, items: [], error: "", loaded: false });
  const [retry, setRetry] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const pendingRef = useRef(false);
  const [authOpen, setAuthOpen] = useState(false);
  const currentToken = useRef(token);

  useEffect(() => {
    currentToken.current = token;
    if (!token) return;
    const controller = new AbortController();
    void getProgrammeWatches(token, controller.signal).then((items) => {
      if (!controller.signal.aborted) setState({ token, items, error: "", loaded: true });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ token, items: [], error: error instanceof Error ? error.message : "Couldn't load your programme watches.", loaded: false });
    });
    return () => controller.abort();
  }, [token, retry]);

  const active = token !== null && state.token === token;
  const items = active ? state.items : [];
  const error = active ? state.error : "";
  const ready = resolved && (!token || (active && state.loaded));
  const reload = useCallback(() => {
    setState((current) => ({ ...current, loaded: false, error: "" }));
    setRetry((value) => value + 1);
  }, []);

  async function toggle(slug: string) {
    if (!resolved) return;
    if (!token) { setAuthOpen(true); return; }
    if (!ready || pendingRef.current) return;
    pendingRef.current = true;
    setPending(slug);
    const watched = items.some((item) => item.programme_slug === slug);
    const previousItems = items;
    if (watched) {
      setState((current) => current.token !== token ? current : {
        ...current,
        items: current.items.filter((item) => item.programme_slug !== slug),
      });
    }
    try {
      const added = watched ? null : await addProgrammeWatch(slug, token);
      if (watched) await removeProgrammeWatch(slug, token);
      if (currentToken.current !== token) return;
      setState((current) => current.token !== token ? current : {
        ...current,
        items: added ? [...current.items, added] : current.items.filter((item) => item.programme_slug !== slug),
      });
      toast.success(watched ? "Stopped watching this programme" : "Programme watched. Look for updates in Notifications and your daily digest when enabled.");
    } catch (error) {
      if (currentToken.current === token) {
        if (watched) setState((current) => current.token !== token ? current : { ...current, items: previousItems });
        toast.error(error instanceof Error ? error.message : "Couldn't update your programme watches. Please try again.");
      }
    } finally {
      pendingRef.current = false;
      setPending(null);
    }
  }

  return <WatchesContext.Provider value={{ ready, loading: !ready && !error, signedIn: !!token, items, error, pending, reload, toggle }}>
    {children}
    <Dialog open={authOpen && !token} onOpenChange={setAuthOpen}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Sign in to watch programmes</DialogTitle>
          <DialogDescription>{WATCH_UPDATES_COPY}</DialogDescription>
        </DialogHeader>
        <AuthWidget />
      </DialogContent>
    </Dialog>
  </WatchesContext.Provider>;
}

export function useProgrammeWatches() {
  const context = useContext(WatchesContext);
  if (!context) throw new Error("Programme watches need a ProgrammeWatchesProvider");
  return context;
}

export function ProgrammeWatchButton({ slug, name }: { slug: string; name: string }) {
  const { ready, items, error, pending, reload, toggle } = useProgrammeWatches();
  const watched = items.some((item) => item.programme_slug === slug);
  if (error) return <Button type="button" variant="outline" className="min-h-11" onClick={reload}>Retry loading watches</Button>;
  return <Button type="button" variant={watched ? "secondary" : "outline"} className="min-h-11" disabled={!ready || pending !== null}
    aria-pressed={watched} aria-label={`${watched ? "Watching" : "Watch & notify"}: ${name}`} onClick={() => void toggle(slug)}>
    {watched ? <BellRing aria-hidden="true" /> : <Bell aria-hidden="true" />}
    {pending === slug ? "Saving…" : watched ? "Watching" : "Watch & notify"}
  </Button>;
}

export function ProgrammeWatchSummary() {
  const { ready, signedIn, items, error, pending, reload, toggle } = useProgrammeWatches();
  return <section aria-labelledby="calendar-watches-heading" className="rounded-xl border border-border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="calendar-watches-heading" className="flex items-center gap-2 text-sm font-semibold"><Bell className="size-4 text-primary" aria-hidden="true" />Watch programmes</h2>
      {signedIn && ready && <span className="text-xs text-muted-foreground">{items.length} of 50 watched</span>}
    </div>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">{WATCH_UPDATES_COPY}</p>
    <Link href="/account?section=notifications" className="inline-flex min-h-11 items-center text-xs text-primary underline underline-offset-4">Manage email preferences</Link>
    {error && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm"><p>{error}</p><Button type="button" variant="outline" className="min-h-11" onClick={reload}>Try again</Button></div>}
    {signedIn && !ready && !error && <p role="status" className="text-xs text-muted-foreground">Loading your watches…</p>}
    {signedIn && ready && items.length > 0 && <details className="mt-2 border-t border-border pt-2">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ChevronDown className="size-4" aria-hidden="true" />Your watched programmes</summary>
      <ul className="divide-y divide-border">{items.map((item) => <li key={item.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 py-2">
        <Link href={`/programme/${encodeURIComponent(item.programme_slug)}`} className="min-w-0 flex-1 basis-40 break-words py-2 text-sm text-primary underline-offset-4 hover:underline">{item.programme_name}</Link>
        <Button type="button" variant="ghost" className="min-h-11" aria-label={`Stop watching ${item.programme_name}`} disabled={pending !== null} onClick={() => void toggle(item.programme_slug)}>{pending === item.programme_slug ? "Saving…" : "Stop watching"}</Button>
      </li>)}</ul>
    </details>}
  </section>;
}

export function ProgrammePageWatch({ slug, name }: { slug: string; name: string }) {
  return <div className="space-y-2"><ProgrammeWatchButton slug={slug} name={name} /><p className="max-w-xl text-xs leading-5 text-muted-foreground">{WATCH_UPDATES_COPY}</p></div>;
}
