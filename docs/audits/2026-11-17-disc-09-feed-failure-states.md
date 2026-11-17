# DISC-09 implementation report — 2026-11-17

Branch: `fix/feed-failure-states`. Frontend implementation only; no backend or infrastructure changes, no dependencies, no commit/push and no Aspirova production requests.

Primary listing failures never become empty success pages. Every primary server list loader uses withBuildFallback: CI/local production builds outside Vercel return the shared failed state with data=null; Vercel builds and runtime rethrow. Failure prerenders show Retry with no count or zero copy. The existing feed/landing/competition client store immediately fetches missing initialData; the calendar and server-only programme/company recovery components do likewise, so offline build shells heal when viewed with an available API.

The success cache validates HTTP status, JSON and list envelopes before storing data. Cached fetch/expiry times remain metadata. Fresh pages render no snapshot notice. Only now >= expiresAt shows: "These results were last updated <relative time> and couldn't be refreshed." The relative text stays in a <time dateTime=ISO> element and Retry calls router.refresh(); visible absolute dates, UTC and cached-snapshot copy were removed. Client-request failures retain query-specific stale Retry.

Empty-filter chips reuse country names, role/role-signal and programme-category configuration, available facet labels, and the existing filter UI wording. Search is labelled "Search: <term>"; unknown parameters get a tidied key without changing URL values. The measured Suspense/remount explanation and supporting storage, scope, snapshot stability and dependency comments have been restored in listingStore.ts and listingResults.ts.

## Surface inventory

| Surface | Before | After |
| --- | --- | --- |
| / server default feed | Build-only fallback could cache zero; runtime already threw; no segment Retry or snapshot time. | CI/local build failure is explicit null with mount-time recovery; Vercel/runtime failures throw; Retry preserves URL. |
| /?filters, pagination, grid and preference changes | Shared store retained some rows, but headers could show initial counts and stale rows had no time; first-load changes hid cards. | Explicit shared states; retained cards; no unverified counts/empty copy; stale timestamp and same-query Retry. |
| Search via ?q= on feed and category pages | API threw, but initial/stale counts could be presented as current; a timed-out original could win a retry race. | HTTP/network/JSON/timeout failure is separate from zero; superseded requests cannot publish; URL filters retained. |
| /jobs, /internships, /remote, /scholarships and /page/[n] | ISR loaders substituted zero during builds; no route failure boundary; generic zero recovery. | Build-phase null shells auto-load; Vercel/runtime failures throw; child boundaries, expired-only notices and useful zero with human chips/calendar. |
| /jobs/in/[place], /jobs/role/[role], internship equivalents | Browse loader used build-only zero fallback; empty action could retain the restrictive filters. | CI/local failed shells recover with the browse base filters; Vercel/runtime throw; parent boundary; human chips preserve remaining filters. |
| /competitions | Build-only zero fallback; client retained rows without times and could show unrelated counts. | Shared validated server/client handling, boundary, stale notices, safe counts and true-zero recovery. |
| /scholarships recurring programme section | Build-only empty programme fallback silently hid data. | CI/local programme failure renders a mount-time recovery component; Vercel/runtime propagate failure and preserve good ISR/deployment. |
| For You (?view=foryou) and /resume profile opportunities | Main store lacked stale timestamps; profile component remounted and discarded old rows on query/retry. | Shared query store preserves results, marks failures stale, ignores superseded responses and retries the same terms/skills. |
| /companies | Caught every failure as []; rendered 0 companies and indexing-empty copy. | CI/local null shells fetch companies on mount; Vercel/runtime throw to the boundary; zero requires a successful array. |
| /companies/[slug] and /page/[n] | Non-404 failures threw, but no local boundary or snapshot label; successful zero had little recovery. | Validated success cache; genuine 404 retained; offline recovery distinguished from 404; inherited boundary and expired-only notice. |
| /programmes and /research | Caught primary failure and rendered an inline message without Retry; research zero could be a blank grid. | Build-phase failure has mount-time programme recovery; Vercel/runtime throw; optional facets stay soft; human chips and useful true zero. |
| /calendar SSR and period loads | SSR caught failure and cached null shell; client retained old period but could show 0 header/facet counts and had no fetched time. | CI/local SSR failure is null with immediate calendar load; Vercel/runtime throw; client retains results/URL filters and hides unknown counts. |
| /saved and saved-count context | Explicit initial error, but refresh failure discarded loaded items; unknown saved counts defaulted to 0. | Same-account snapshots retained across retry/token refresh; stale timestamped Retry; unknown context count is null; zero onboarding only on success/local removal. |
| Similar opportunities on opportunity details | API helper swallowed failures into []; detail caller also caught; empty widget hidden. | Helper now throws; existing detail caller hides this decorative section on failure, with no zero count or false empty message. |
| Trending/MostViewed, top companies, stats, matched programmes | Trending swallowed into empty; others hid/cleared failed widgets; no displayed failure zero in most cases. | Trending throws to caller which hides it; top/matched use shared list states and hide failures; stats retain quiet hidden/unavailable behavior. |
| Facet/filter counts and list headers | Per-option feed count helper returned 0 on error; unavailable filters could be disabled; calendar could count absent data as zero. | Count-request failure propagates; unknown counts omitted, filters usable with direct entry; failed headers/facets omit numeric counts. |
| CompanyPicker search and account followed companies | Picker cleared suggestions on failure; account CompanyAlerts hid existing rows during refresh/failure. | Shared failed state retains prior rows/suggestions with time and Retry; no false empty or numeric failure count. CompanyAlerts is the necessary PR #206 overlap. |
| Watched programmes (calendar summary and account settings) | Failed fetch discarded rows; retry hid the list. | Same-account rows retained, stale time shown, bounded/cancellable requests and explicit Retry. |
| Recently viewed; curated SourceCompanyCard/SourceCompanyDetail programmes | Local storage snapshots or deterministic registry data; no listing API failure involved. | Unchanged: local failures hide recent widget; static source/programme links remain usable. |
| Dormant Pro resume-match list | RESUME_MATCHES_ENABLED=false; no live listing API path. Existing submission error already separate from empty. | Unchanged and remains disabled; the active deterministic profile list is covered above. |

## Validation

- `node node_modules/eslint/bin/eslint.js .`: clean.
- `node node_modules/typescript/bin/tsc --noEmit`: clean.
- `node --test lib/*.test.mjs`: 209 tests passed. All frontend node suites were run; no current test paths contain brackets.
- New correction tests cover CI/local failed/null, Vercel/runtime rethrows, true-zero success, automatic default-feed and programme/company recovery on mount, fresh notice -> nothing, expiry boundary -> relative notice and router.refresh Retry, human country/role/category/facet labels, and unknown/repeated-filter preservation.
- Existing request-race, HTTP/network/JSON/timeout, SSR feed/search and calendar regressions also pass.

## Production build and ISR check

Environment: NEXT_PUBLIC_API_URL=http://localhost:8000, NEXT_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co, NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder, VERCEL=0. Localhost:8000 was confirmed ECONNREFUSED. No API fixture/server was started.

- Exact `node node_modules/next/dist/bin/next build --webpack` with normal fonts: blocked before prerendering by sandbox EACCES on Google Fonts downloads (Inter, Geist Mono, Source Serif 4).
- Repeated with the same API/Supabase values and Next's test-only NEXT_FONT_GOOGLE_MOCKED_RESPONSES fixture stored under %TEMP%: PASS; 84 static pages generated. Only font CSS/assets were mocked; the API stayed unavailable. No font source or CI configuration was changed.
- `node scripts/check-isr-registration.mjs` after that build: PASS, 12 dynamic ISR registrations and six static landing routes at their expected revalidate windows.
- Generated HTML inspection checked all 49 offline listing prerenders (base pages plus city/role pages): each shows failure content and none contains false-zero counts/copy.

## Review notes / untested

- The unmocked production build remains externally blocked by this sandbox's Google Fonts network restriction. The build/ISR result above is explicitly the font-fixture run, not an unmodified-font build.
- No live browser session or full failure-after-success ISR lifecycle was exercised. Mount-time healing is covered through the actual client store/recovery components with isolated hooks and mocked APIs; actual generated HTML and prerender registration were checked.
- Healthy snapshots show no notice. Expiry determines the stale notice and its relative time; the ISO fetch timestamp remains in dateTime only.
- `components/account/NotificationsSection.tsx` remains the only PR #206 overlap from the initial implementation. Correction round 1 does not expand that edit. `lib/types.ts`, opportunity detail, OpportunityCard, ReportIssueDialog and jobPostingJsonLd.ts remain untouched.

## Correction round 1

1. Restored build-aware failure states and automatic client healing across changed server list loaders; no []/total=0 fallback. Runtime and Vercel failures still propagate.
2. Removed the always-visible snapshot strip. Only expired pages show the requested relative-time failure notice and router.refresh Retry.
3. Restored WHY THIS EXISTS at the top of listingStore.ts, kept a pointer in listingResults.ts, and restored/adapted the substantive supporting comments from the refactor diff.
4. Replaced raw chip labels with existing human labels and added tests.

## Files changed

- `frontend/app/(feed)/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/(feed)/page.tsx` — Use explicit null CI/local fallback with automatic client recovery; Vercel/runtime throw; hide failed decorative fetches.
- `frontend/app/calendar/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/calendar/page.tsx` — Use build-aware null failure and calendar mount-time recovery; Vercel/runtime throw.
- `frontend/app/companies/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/companies/page.tsx` — Remove catch-to-empty; add dated success and useful true-zero content.
- `frontend/app/competitions/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/competitions/page.tsx` — Use null build fallback and automatic competition recovery; runtime/Vercel throw.
- `frontend/app/internships/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/internships/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/app/internships/page/[n]/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/app/jobs/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/jobs/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/app/jobs/page/[n]/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/app/programmes/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/programmes/page.tsx` — Throw primary failures; keep optional facets soft; add dated results and removable zero-state filters.
- `frontend/app/remote/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/remote/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/app/remote/page/[n]/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/app/research/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/research/page.tsx` — Throw primary failures; distinguish true zero and provide recovery suggestions.
- `frontend/app/saved/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/saved/page.tsx` — Preserve same-account results across failed refreshes/token rotation; stale Retry; useful empty state.
- `frontend/app/scholarships/error.tsx` — Delegate segment failure to shared URL-preserving Retry boundary.
- `frontend/app/scholarships/page.tsx` — Propagate scholarship-programme failure and pass snapshot metadata.
- `frontend/app/scholarships/page/[n]/page.tsx` — Pass snapshot fetch/expiry metadata into the shared landing.
- `frontend/components/BookmarksProvider.tsx` — Represent unknown saved counts as null.
- `frontend/components/BrowsePage.tsx` — Date cached results and make zero-state chips/clear links actually broaden the browse view.
- `frontend/components/CompanyOpportunities.tsx` — Date company results and add useful successful-zero recovery.
- `frontend/components/CompanyPicker.tsx` — Preserve suggestions on search failure with timestamped Retry.
- `frontend/components/CompetitionsAdvancedFilters.tsx` — Wire shared listing states and failure feedback.
- `frontend/components/CompetitionsResults.tsx` — Wire shared listing states and failure feedback.
- `frontend/components/CountedAdvancedFilterShell.tsx` — Keep options whose count is unknown.
- `frontend/components/CountedFilterControls.tsx` — Make counts optional; keep unknown options usable; permit direct filters when facets fail.
- `frontend/components/FacetPicker.tsx` — Separate an unavailable option list from no matches; permit direct filter entry.
- `frontend/components/FeedGrid.tsx` — Use shared true-zero suggestions, removable filters and calendar link.
- `frontend/components/FeedResults.tsx` — Suppress unverified counts; preserve cards; use query-specific Retry/Refresh and timestamps.
- `frontend/components/HiringCalendar.tsx` — Preserve data on failure; suppress false-zero headers/facets; retry the same period; wire zero-state URL controls.
- `frontend/components/ListingErrorBoundary.tsx` — Shared segment failure content with reset()/refresh Retry and no navigation.
- `frontend/components/ListingFeedback.tsx` — Shared failure UI; expiry-only relative-time notice with router.refresh Retry; human removable chips and accessible recovery actions.
- `frontend/components/ListingResultsState.tsx` — Share stale/failure feedback; preserve visible cards during retry; suppress empty copy after failure.
- `frontend/components/MatchedProgrammes.tsx` — Use explicit list states; hide failed decorative matches.
- `frontend/components/OpportunityLandingPage.tsx` — Carry fetched/expiry times through server fallback and client results.
- `frontend/components/OpportunityLandingResults.tsx` — Preserve results with stale notices, suppress unknown counts and keep Retry query-specific.
- `frontend/components/OpportunityListingFilters.tsx` — Use unknown counts on failure and keep filters interactive.
- `frontend/components/ProfileOpportunities.tsx` — Use shared results store; retain profile matches through failures and superseded requests.
- `frontend/components/ProgrammesAdvancedFilters.tsx` — Wire shared listing states and failure feedback.
- `frontend/components/TopCompanies.tsx` — Use explicit results/empty/failed states; hide failed widget.
- `frontend/components/account/NotificationsSection.tsx` — Required PR #206 overlap: only CompanyAlerts imports/state/rendering; retain followed-company rows with timestamped Retry.
- `frontend/components/account/WatchedProgrammesSection.tsx` — Keep watched rows below shared stale feedback.
- `frontend/components/calendar/Filters.tsx` — Hide counts while loading or after failed refresh, keeping category controls usable.
- `frontend/components/calendar/ProgrammeWatches.tsx` — Retain only same-account watch snapshots; expose last successful load time and stale Retry.
- `frontend/lib/api.ts` — Use validated listing transport; propagate trending/similar failures; validate authenticated arrays and bound reads.
- `frontend/lib/browse.ts` — Use build-aware null fallback rather than empty data.
- `frontend/lib/feedQuery.ts` — Add optional snapshot timestamps without changing lib/types.ts.
- `frontend/lib/hiringCalendar.test.mjs` — Load actual calendar TS through isolated mockable loader after adding the cached transport import.
- `frontend/lib/hiringCalendar.ts` — Fetch validated calendar data; add optional snapshot timestamps.
- `frontend/lib/landing.ts` — Use build-aware null fallback and preserve successful snapshot metadata.
- `frontend/lib/listState.test.mjs` — Unit coverage for success/zero, HTTP failures, network/JSON failures, supersession and filter preservation.
- `frontend/lib/listState.ts` — Shared states/status guard/sequence gate; filter-removal links use country, role/category and facet labels.
- `frontend/lib/listingFetch.ts` — Cache validated successes in time buckets; timeout requests; attach fetched/expiry times; never cache failures as empty.
- `frontend/lib/listingRendering.test.mjs` — Render real feed/search components and server feed; verify no false zero, true-zero recovery, stale notices, expired-cache failure and usable facets.
- `frontend/lib/listingResults.test.mjs` — Exercise explicit states, exact-query retries, timeouts, route isolation and superseded responses.
- `frontend/lib/listingResults.ts` — Keep the existing external-store/Suspense pattern and delegate to the shared store.
- `frontend/lib/listingStore.ts` — Shared bounded store retaining successful data and rejecting superseded completions; restored WHY THIS EXISTS and storage/snapshot comments.
- `frontend/lib/opportunityListingQuery.ts` — Propagate count-request failure; unknown default counts instead of zero.
- `frontend/lib/programmeWatches.ts` — Bound authenticated reads and validate the returned watch array.
- `frontend/lib/programmesQuery.ts` — Retain validated snapshot metadata in the inferred return type.
- `frontend/scripts/test-module.mjs` — Dependency-free test loader for real TS/TSX modules with mocked services and hooks.
- `docs/audits/2026-11-17-disc-09-feed-failure-states.md` — Complete surface inventory, per-file changes, verification and review limitations.
- `frontend/lib/buildFallback.ts` — Return failed/null only for CI/local builds outside Vercel; rethrow Vercel/runtime failures; document all three cases.
- `frontend/lib/buildFallback.test.mjs` — Build-mode policy, genuine zero and automatic offline-shell healing regressions.
- `frontend/components/BuildListingRecovery.tsx` — Automatic mount-time programme/company list recovery for explicit offline build shells.
- `frontend/app/companies/[slug]/page.tsx` — Distinguish failed build state from genuine missing company and hydrate unavailable lists.
- `frontend/app/companies/[slug]/page/[n]/page.tsx` — Keep paginated company failure/404 distinct and add build-shell recovery.
