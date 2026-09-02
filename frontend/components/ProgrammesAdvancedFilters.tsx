"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
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
  FilterPanelSection,
  type ActiveFilterChip,
} from "@/components/CountedFilterControls";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { PROGRAMME_FILTER_PARAM_KEYS } from "@/lib/programmesQuery";
import type { Facets } from "@/lib/types";

export type ProgrammesFacetsStatus = CountedFacetsStatus;
type MultiFilterKey = (typeof PROGRAMME_FILTER_PARAM_KEYS)[number];

interface ProgrammesFacetsState {
  facets: Facets | null;
  facetsStatus: ProgrammesFacetsStatus;
}

interface ProgrammesFilterProps extends ProgrammesFacetsState {
  path: "/research" | "/programmes";
  activeFilterLabel: string;
  panelLabel: string;
  mobileDescription: string;
}

function programmesHref(path: string, params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function getProgrammesActiveFilterCount(searchParams: SearchParamReader): number {
  return PROGRAMME_FILTER_PARAM_KEYS.reduce(
    (count, key) => count + activeValues(searchParams, key).length,
    0,
  );
}

function ProgrammesFiltersPanel({
  facets,
  facetsStatus,
  path,
  isPending,
  idPrefix,
  onClose,
}: ProgrammesFacetsState & {
  path: "/research" | "/programmes";
  isPending: boolean;
  idPrefix: string;
  onClose?: () => void;
}) {
  const searchParams = useSearchParams();
  const { navigate } = useFeedNavigation();
  const [organiserSearch, setOrganiserSearch] = useState("");

  function commit(params: URLSearchParams, resetPage = true) {
    if (resetPage) params.delete("page");
    navigate(programmesHref(path, params));
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

  function clearAllFilters() {
    const params = new URLSearchParams(searchParams.toString());
    for (const key of PROGRAMME_FILTER_PARAM_KEYS) {
      params.delete(key);
    }
    params.delete("q");
    commit(params);
    onClose?.();
  }

  const categoryOptions = countedOptions(facets?.programme_categories);
  const fieldOptions = countedOptions(facets?.programme_fields);
  const organiserOptions = countedOptions(facets?.programme_organisers);
  const institutionTypeOptions = countedOptions(facets?.programme_institution_types);
  const statusOptions = countedOptions(facets?.programme_statuses);
  const organiserNeedle = organiserSearch.trim().toLowerCase();
  const visibleOrganiserOptions = useMemo(() => {
    if (!organiserNeedle) return organiserOptions;
    return organiserOptions.filter((option) =>
      option.label.toLowerCase().includes(organiserNeedle),
    );
  }, [organiserNeedle, organiserOptions]);
  const emptyLabel = countedStatusLabel(facetsStatus);
  const activeFilterCount = getProgrammesActiveFilterCount(searchParams);
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

      <FilterPanelSection title="Category">
        <CountedMultiSelectGroup
          label="Programme category"
          options={categoryOptions}
          values={activeValues(searchParams, "category")}
          onToggle={(value) => toggleMultiParam("category", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Field">
        <CountedMultiSelectGroup
          label="Programme field"
          options={fieldOptions}
          values={activeValues(searchParams, "field")}
          onToggle={(value) => toggleMultiParam("field", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Organiser">
        <div className="grid gap-3">
          <Label htmlFor={`${idPrefix}-organiser-search`} className="sr-only">
            Search organisers
          </Label>
          <Input
            id={`${idPrefix}-organiser-search`}
            type="search"
            placeholder="Search organisers"
            value={organiserSearch}
            disabled={isPending || facetsStatus !== "loaded"}
            onChange={(event) => setOrganiserSearch(event.target.value)}
          />
          <CountedMultiSelectGroup
            label="Programme organiser"
            options={visibleOrganiserOptions}
            values={activeValues(searchParams, "organiser")}
            onToggle={(value) => toggleMultiParam("organiser", value)}
            disabled={isPending || facetsStatus !== "loaded"}
            emptyLabel={organiserNeedle ? "No organiser matches" : emptyLabel}
          />
        </div>
      </FilterPanelSection>

      <FilterPanelSection title="Institution type">
        <CountedMultiSelectGroup
          label="Institution type"
          options={institutionTypeOptions}
          values={activeValues(searchParams, "institution_type")}
          onToggle={(value) => toggleMultiParam("institution_type", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
      </FilterPanelSection>

      <FilterPanelSection title="Application status">
        <CountedMultiSelectGroup
          label="Application status"
          options={statusOptions}
          values={activeValues(searchParams, "status")}
          onToggle={(value) => toggleMultiParam("status", value)}
          disabled={isPending || facetsStatus !== "loaded"}
          emptyLabel={emptyLabel}
        />
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

export function ProgrammesAdvancedFilters({
  facets,
  facetsStatus,
  path,
  activeFilterLabel,
  panelLabel,
  mobileDescription,
}: ProgrammesFilterProps) {
  const searchParams = useSearchParams();
  const { isFeedPending: isPending } = useFeedNavigation();
  const activeFilterCount = getProgrammesActiveFilterCount(searchParams);

  return (
    <CountedAdvancedFilterShell
      activeFilterCount={activeFilterCount}
      activeFilterLabel={activeFilterLabel}
      isPending={isPending}
      panelLabel={panelLabel}
      mobileDescription={mobileDescription}
      idPrefixBase="programme-filter"
    >
      {({ idPrefix, onClose }) => (
        <ProgrammesFiltersPanel
          facets={facets}
          facetsStatus={facetsStatus}
          path={path}
          isPending={isPending}
          idPrefix={idPrefix}
          onClose={onClose}
        />
      )}
    </CountedAdvancedFilterShell>
  );
}

export function ProgrammesActiveFilterChips({
  facets,
  path,
}: {
  facets: Facets | null;
  path: "/research" | "/programmes";
}) {
  const searchParams = useSearchParams();
  const { navigate, isFeedPending: isPending } = useFeedNavigation();

  function commit(params: URLSearchParams, resetPage = true) {
    if (resetPage) params.delete("page");
    navigate(programmesHref(path, params));
  }

  function removeMultiParam(key: MultiFilterKey, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    const nextValues = activeValues(searchParams, key).filter(
      (currentValue) => currentValue !== value,
    );
    setRepeatedParam(params, key, nextValues);
    commit(params);
  }

  function removeSingleParam(key: "q") {
    const params = new URLSearchParams(searchParams.toString());
    params.delete(key);
    commit(params);
  }

  function clearAllFilters() {
    const params = new URLSearchParams(searchParams.toString());
    for (const key of PROGRAMME_FILTER_PARAM_KEYS) {
      params.delete(key);
    }
    params.delete("q");
    commit(params);
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
    ...activeValues(searchParams, "category").map((value) => {
      const label = optionLabel(facets?.programme_categories, value);
      return {
        id: `category:${value}`,
        label,
        humanLabel: `Category: ${label}`,
        onRemove: () => removeMultiParam("category", value),
      };
    }),
    ...activeValues(searchParams, "field").map((value) => {
      const label = optionLabel(facets?.programme_fields, value);
      return {
        id: `field:${value}`,
        label,
        humanLabel: `Field: ${label}`,
        onRemove: () => removeMultiParam("field", value),
      };
    }),
    ...activeValues(searchParams, "organiser").map((value) => {
      const label = optionLabel(facets?.programme_organisers, value);
      return {
        id: `organiser:${value}`,
        label,
        humanLabel: `Organiser: ${label}`,
        onRemove: () => removeMultiParam("organiser", value),
      };
    }),
    ...activeValues(searchParams, "institution_type").map((value) => {
      const label = optionLabel(facets?.programme_institution_types, value);
      return {
        id: `institution_type:${value}`,
        label,
        humanLabel: `Institution type: ${label}`,
        onRemove: () => removeMultiParam("institution_type", value),
      };
    }),
    ...activeValues(searchParams, "status").map((value) => {
      const label = optionLabel(facets?.programme_statuses, value);
      return {
        id: `status:${value}`,
        label,
        humanLabel: `Application status: ${label}`,
        onRemove: () => removeMultiParam("status", value),
      };
    }),
  );

  return (
    <ActiveFilterChips
      filters={filters}
      disabled={isPending}
      onClearAll={clearAllFilters}
    />
  );
}
