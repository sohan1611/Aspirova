"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  activeSingleValue,
  activeValues,
  countedOptions,
  countedStatusLabel,
  CountedAdvancedFilterShell,
  optionLabel,
  setRepeatedParam,
  type CountedFacetsStatus,
  type SearchParamReader,
} from "@/components/CountedAdvancedFilterShell";
import {
  ActiveFilterChips,
  CountedMultiSelectGroup,
  CountedSingleSelectGroup,
  FilterPanelSection,
  type ActiveFilterChip,
} from "@/components/CountedFilterControls";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { getFacets } from "@/lib/api";
import { COMPETITION_FILTER_PARAM_KEYS } from "@/lib/competitionsQuery";
import type { Facets } from "@/lib/types";

const COMPETITIONS_PATH = "/competitions";
const DEBOUNCE_MS = 300;

export type CompetitionFacetsStatus = CountedFacetsStatus;
type MultiFilterKey = "comp_type" | "organiser_type" | "mode";
type SingleFilterKey = "registration" | "deadline_within";

interface CompetitionFacetsState {
  facets: Facets | null;
  facetsStatus: CompetitionFacetsStatus;
}

let competitionFacetsCache: Facets | null = null;
let competitionFacetsPromise: Promise<Facets> | null = null;

function loadCompetitionFacetsOnce(): Promise<Facets> {
  if (!competitionFacetsPromise) {
    competitionFacetsPromise = getFacets({ kind: "competitions" }).then((facets) => {
      competitionFacetsCache = facets;
      return facets;
    });
  }

  return competitionFacetsPromise;
}

export function useCompetitionFacets(): CompetitionFacetsState {
  const [facets, setFacets] = useState<Facets | null>(competitionFacetsCache);
  const [facetsStatus, setFacetsStatus] = useState<CompetitionFacetsStatus>(
    competitionFacetsCache ? "loaded" : "loading",
  );

  useEffect(() => {
    if (competitionFacetsCache) return;

    let cancelled = false;
    void loadCompetitionFacetsOnce()
      .then((nextFacets) => {
        if (!cancelled) {
          setFacets(nextFacets);
          setFacetsStatus("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFacets({
            companies: [],
            locations: [],
            comp_types: [],
            registrations: [],
            deadline_within: [],
            organiser_types: [],
            modes: [],
          });
          setFacetsStatus("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { facets, facetsStatus };
}

function formatPrize(value: string): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(parsed);
}

function competitionHref(params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${COMPETITIONS_PATH}?${query}` : COMPETITIONS_PATH;
}

function parsePrizeInput(value: string): string | null | undefined {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return undefined;

  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed)) return undefined;
  return String(parsed);
}

export function getCompetitionActiveFilterCount(searchParams: SearchParamReader): number {
  return (
    activeValues(searchParams, "comp_type").length +
    activeValues(searchParams, "organiser_type").length +
    activeValues(searchParams, "mode").length +
    (activeSingleValue(searchParams, "registration") ? 1 : 0) +
    (activeSingleValue(searchParams, "deadline_within") ? 1 : 0) +
    (activeSingleValue(searchParams, "prize_min") ? 1 : 0)
  );
}

function CompetitionFiltersPanel({
  facets,
  facetsStatus,
  isPending,
  idPrefix,
  onClose,
}: CompetitionFacetsState & {
  isPending: boolean;
  idPrefix: string;
  onClose?: () => void;
}) {
  const searchParams = useSearchParams();
  const { navigate } = useFeedNavigation();
  const paramsSignature = searchParams.toString();
  const currentPrizeParam = searchParams.get("prize_min") ?? "";
  const [prizeInput, setPrizeInput] = useState(currentPrizeParam);
  const [syncedPrizeParam, setSyncedPrizeParam] = useState(currentPrizeParam);

  if (currentPrizeParam !== syncedPrizeParam) {
    setSyncedPrizeParam(currentPrizeParam);
    setPrizeInput(currentPrizeParam);
  }

  function commit(params: URLSearchParams, resetPage = true) {
    if (resetPage) params.delete("page");
    navigate(competitionHref(params));
  }

  function toggleMultiParam(key: MultiFilterKey, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    const values = activeValues(searchParams, key);
    const nextValues = values.includes(value)
      ? values.filter((currentValue) => currentValue !== value)
      : [...values, value];
    setRepeatedParam(params, key, nextValues);
    commit(params);
  }

  function setSingleParam(key: SingleFilterKey, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    commit(params);
  }

  function clearAllFilters() {
    const params = new URLSearchParams(searchParams.toString());
    for (const key of COMPETITION_FILTER_PARAM_KEYS) {
      params.delete(key);
    }
    commit(params, false);
    onClose?.();
  }

  useEffect(() => {
    const parsed = parsePrizeInput(prizeInput);
    if (parsed === undefined) return;

    const currentValue = currentPrizeParam || null;
    if (parsed === currentValue) return;

    const timeout = window.setTimeout(() => {
      const params = new URLSearchParams(paramsSignature);
      if (parsed === null) params.delete("prize_min");
      else params.set("prize_min", parsed);
      commit(params);
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prizeInput, currentPrizeParam, paramsSignature]);

  const compTypeOptions = countedOptions(facets?.comp_types);
  const registrationOptions = countedOptions(facets?.registrations);
  const deadlineOptions = countedOptions(facets?.deadline_within);
  const organiserTypeOptions = countedOptions(facets?.organiser_types);
  const modeOptions = countedOptions(facets?.modes);
  const emptyLabel = countedStatusLabel(facetsStatus);
  const activeFilterCount = getCompetitionActiveFilterCount(searchParams);
  const hasActiveFilters = activeFilterCount > 0;

  return (
    <div aria-busy={isPending} className="space-y-5 p-4">
      {facetsStatus === "loading" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2
            className="h-4 w-4 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          Loading counts...
        </p>
      )}
      {facetsStatus === "error" && (
        <p className="text-sm text-muted-foreground" role="status">
          Counts unavailable.
        </p>
      )}

      <FilterPanelSection title="Type">
        <CountedMultiSelectGroup
          label="Competition type"
          options={compTypeOptions}
          values={activeValues(searchParams, "comp_type")}
          onToggle={(value) => toggleMultiParam("comp_type", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Registration">
        <CountedSingleSelectGroup
          label="Registration"
          options={registrationOptions}
          value={activeSingleValue(searchParams, "registration")}
          onSelect={(value) => setSingleParam("registration", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Deadline">
        <CountedSingleSelectGroup
          label="Registration deadline"
          options={deadlineOptions}
          value={activeSingleValue(searchParams, "deadline_within")}
          onSelect={(value) => setSingleParam("deadline_within", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Organizer type">
        <CountedMultiSelectGroup
          label="Organizer type"
          options={organiserTypeOptions}
          values={activeValues(searchParams, "organiser_type")}
          onToggle={(value) => toggleMultiParam("organiser_type", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Mode">
        <CountedMultiSelectGroup
          label="Competition mode"
          options={modeOptions}
          values={activeValues(searchParams, "mode")}
          onToggle={(value) => toggleMultiParam("mode", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Prize">
        <div className="grid gap-2">
          <Label htmlFor={`${idPrefix}-prize-min`} className="sr-only">
            Minimum prize in INR
          </Label>
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              INR
            </span>
            <Input
              id={`${idPrefix}-prize-min`}
              type="number"
              min={0}
              step={1000}
              inputMode="numeric"
              placeholder="Any prize"
              value={prizeInput}
              disabled={isPending}
              aria-label="Minimum prize in INR"
              onChange={(event) => setPrizeInput(event.target.value)}
              className="pl-12"
            />
          </div>
        </div>
      </FilterPanelSection>

      {hasActiveFilters && (
        <>
          <Separator />
          <div className="flex justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isPending}
              onClick={clearAllFilters}
            >
              Clear all
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export function CompetitionsAdvancedFilters({
  facets,
  facetsStatus,
}: CompetitionFacetsState) {
  const searchParams = useSearchParams();
  const { isFeedPending: isPending } = useFeedNavigation();
  const activeFilterCount = getCompetitionActiveFilterCount(searchParams);

  return (
    <CountedAdvancedFilterShell
      activeFilterCount={activeFilterCount}
      activeFilterLabel="competition filters"
      isPending={isPending}
      panelLabel="Competition filters"
      mobileDescription="Counted competition filters"
      idPrefixBase="competition-filter"
    >
      {({ idPrefix, onClose }) => (
        <CompetitionFiltersPanel
          facets={facets}
          facetsStatus={facetsStatus}
          isPending={isPending}
          idPrefix={idPrefix}
          onClose={onClose}
        />
      )}
    </CountedAdvancedFilterShell>
  );
}

export function CompetitionsActiveFilterChips({ facets }: { facets: Facets | null }) {
  const searchParams = useSearchParams();
  const { navigate, isFeedPending: isPending } = useFeedNavigation();

  function commit(params: URLSearchParams, resetPage = true) {
    if (resetPage) params.delete("page");
    navigate(competitionHref(params));
  }

  function removeMultiParam(key: MultiFilterKey, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    const nextValues = activeValues(searchParams, key).filter(
      (currentValue) => currentValue !== value,
    );
    setRepeatedParam(params, key, nextValues);
    commit(params);
  }

  function removeSingleParam(key: SingleFilterKey | "prize_min" | "q") {
    const params = new URLSearchParams(searchParams.toString());
    params.delete(key);
    commit(params);
  }

  function clearAllFilters() {
    const params = new URLSearchParams(searchParams.toString());
    for (const key of COMPETITION_FILTER_PARAM_KEYS) {
      params.delete(key);
    }
    commit(params, false);
  }

  const filters: ActiveFilterChip[] = [];
  const q = activeSingleValue(searchParams, "q");
  if (q) {
    filters.push({
      id: "q",
      label: `Search: "${q}"`,
      humanLabel: `Search: "${q}"`,
      onRemove: () => removeSingleParam("q"),
    });
  }

  filters.push(
    ...activeValues(searchParams, "comp_type").map((value) => {
      const label = optionLabel(facets?.comp_types, value);
      return {
        id: `comp_type:${value}`,
        label,
        humanLabel: `Type: ${label}`,
        onRemove: () => removeMultiParam("comp_type", value),
      };
    }),
    ...activeValues(searchParams, "organiser_type").map((value) => {
      const label = optionLabel(facets?.organiser_types, value);
      return {
        id: `organiser_type:${value}`,
        label,
        humanLabel: `Organizer type: ${label}`,
        onRemove: () => removeMultiParam("organiser_type", value),
      };
    }),
    ...activeValues(searchParams, "mode").map((value) => {
      const label = optionLabel(facets?.modes, value);
      return {
        id: `mode:${value}`,
        label,
        humanLabel: `Mode: ${label}`,
        onRemove: () => removeMultiParam("mode", value),
      };
    }),
  );

  const registration = activeSingleValue(searchParams, "registration");
  if (registration) {
    const label = optionLabel(facets?.registrations, registration);
    filters.push({
      id: "registration",
      label,
      humanLabel: `Registration: ${label}`,
      onRemove: () => removeSingleParam("registration"),
    });
  }

  const deadlineWithin = activeSingleValue(searchParams, "deadline_within");
  if (deadlineWithin) {
    const label = optionLabel(facets?.deadline_within, deadlineWithin);
    filters.push({
      id: "deadline_within",
      label,
      humanLabel: `Deadline: ${label}`,
      onRemove: () => removeSingleParam("deadline_within"),
    });
  }

  const prizeMin = activeSingleValue(searchParams, "prize_min");
  if (prizeMin) {
    const label = (
      <>
        Prize at least INR <span className="tnum">{formatPrize(prizeMin)}</span>
      </>
    );
    filters.push({
      id: "prize_min",
      label,
      humanLabel: `Prize at least INR ${formatPrize(prizeMin)}`,
      onRemove: () => removeSingleParam("prize_min"),
    });
  }

  return (
    <ActiveFilterChips
      filters={filters}
      disabled={isPending}
      onClearAll={clearAllFilters}
      showClearAll={filters.some((filter) => filter.id !== "q")}
    />
  );
}
