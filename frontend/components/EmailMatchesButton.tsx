"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useId, useState } from "react";
import { toast } from "sonner";
import AuthWidget from "@/components/AuthWidget";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createSavedSearch, getSavedSearches, updateSavedSearch } from "@/lib/api";
import { canonicalSavedSearchParams, savedSearchSummary } from "@/lib/savedSearchParams";
import type { SavedSearchItem, SavedSearchParams } from "@/lib/types";
import { useSession } from "@/lib/useSession";

export default function EmailMatchesButton(props: { params: SavedSearchParams; disabled?: boolean }) {
  return <Suspense fallback={null}><EmailMatchesButtonContent {...props} /></Suspense>;
}

function EmailMatchesButtonContent({
  params,
  disabled = false,
}: {
  params: SavedSearchParams;
  disabled?: boolean;
}) {
  const session = useSession();
  const accessToken = session?.access_token;
  const searchParams = useSearchParams();
  const editSearch = searchParams.get("editSearch");
  const editing = editSearch !== null && /^[0-9]+$/.test(editSearch) && Boolean(accessToken);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [alertsEnabled, setAlertsEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [loadedSearches, setLoadedSearches] = useState<SavedSearchItem[]>([]);

  useEffect(() => {
    if (!open || !accessToken || !editing) return;
    let cancelled = false;
    getSavedSearches(accessToken).then((items) => {
      if (!cancelled) setLoadedSearches(items);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [accessToken, editing, open]);

  const duplicateFilters = editing && loadedSearches.some((item) =>
    item.id !== Number(editSearch) &&
    canonicalSavedSearchParams(item.params) === canonicalSavedSearchParams(params));

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || saving) return;
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateSavedSearch(accessToken, Number(editSearch), { params });
        toast.success("Saved search updated", {
          action: { label: "Saved searches", onClick: () => { window.location.href = "/account?section=saved"; } },
        });
      } else {
        await createSavedSearch(accessToken, {
          name: name.trim() || null,
          params,
          alerts_enabled: alertsEnabled,
        });
        toast.success(alertsEnabled ? "We'll email you new matches" : "Search saved", {
          action: { label: "Settings", onClick: () => { window.location.href = "/account?section=saved"; } },
        });
      }
      setOpen(false);
    } catch (error) {
      setError(error instanceof Error ? error.message : "We couldn't save this search. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (Object.keys(params).length === 0) return null;

  return (
    <>
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => {
        setLoadedSearches([]);
        setName("");
        setAlertsEnabled(true);
        setError(null);
        setOpen(true);
      }}>
        {editing ? "Update saved search" : "Email me new matches"}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          {accessToken ? (
            <form onSubmit={handleSave} className="grid gap-5">
              <DialogHeader>
                <DialogTitle className="font-serif text-2xl">{editing ? "Update saved search" : "Save this search"}</DialogTitle>
                <DialogDescription>{editing ? "Replace the filters for this saved search." : "Save these filters and receive new matches by email."}</DialogDescription>
              </DialogHeader>
              {!editing && <>
              <div className="grid gap-2.5">
                <Label className="eyebrow" htmlFor={id + "-name"}>
                  Name <span className="normal-case text-muted-foreground">(optional)</span>
                </Label>
                <Input id={id + "-name"} value={name} maxLength={80} disabled={saving}
                  onChange={(event) => setName(event.target.value)} placeholder={savedSearchSummary(params)} />
              </div>
              <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/40 px-3 py-3">
                <input id={id + "-alerts"} type="checkbox" checked={alertsEnabled} disabled={saving}
                  onChange={(event) => setAlertsEnabled(event.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-border bg-background accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50" />
                <div className="min-w-0">
                  <Label htmlFor={id + "-alerts"} className="cursor-pointer">Email alerts</Label>
                  <p className="mt-0.5 text-sm text-muted-foreground">We&apos;ll email you new matches.</p>
                </div>
              </div>
              </>}
              {duplicateFilters && <p role="status" className="text-xs text-muted-foreground">Another saved search already uses these filters.</p>}
              {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
              <DialogFooter>
                <Button type="button" variant="outline" disabled={saving} onClick={() => setOpen(false)}>Cancel</Button>
                <Button type="submit" disabled={saving}>{saving ? "Saving…" : editing ? "Update saved search" : "Save search"}</Button>
              </DialogFooter>
            </form>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Sign in to save this search</DialogTitle>
                <DialogDescription>Receive new matches by email. Your filters will stay here.</DialogDescription>
              </DialogHeader>
              <AuthWidget />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
