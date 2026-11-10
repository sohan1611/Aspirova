# Feature specification inventory

Date 2026-11-10. Master and worktree HEAD `9d5b629da78d640751940f6b2449ede806a165dc` (PR #163).

Method used code read-only inspection of routes, components, models, migrations, workers, workflows and existing test sources. No production database access, API calls, rendered-page inspection or execution of tests, builds, servers or migrations occurred. `Done` describes implemented behavior evidenced in code, with runtime acceptance still unverified. `VERIFY` in the outside specification supplies no bug evidence.

Coverage is 143 unique IDs across 15 section tables. Status totals are Done 7, Improve 110, Missing 7, Ruled out 1, Blocked 3 and Not now 15. Binding prohibitions take precedence over future priority, including FUT-01.

Sizes estimate the remaining work, including verification. Migration means a proposed schema change or required production backfill, identified explicitly. Founder means shipping requires a founder action or product decision. Proposed Batch 1 deliberately selects narrower, independently useful slices of broad feature IDs. Evidence paths are repository-relative. Missing entries identify the inspected surface that lacks the capability.

Binding bounds apply throughout. `CLAUDE.md` defers all AI. `docs/README.md` 2026-11-02 requires sign-in for Apply (PR #132), with comparison due around 2026-11-16. That experiment stays closed to changes here. The 2026-11-03 pricing ruling permits selling only running features. The 2026-11-04 destination ruling holds new stored verification/provenance dates pending measured need. Programme content and opening verification follow the 2026-07-31 and 2026-08-04 rulings. `CLAUDE.md` forbids Dependabot. Future implementation must satisfy Doc 08 §3 and the 2026-08-17 real-data/rendered-DOM merge gate.

## 1. Homepage, navigation and onboarding

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| H-01 | Improve | `frontend/components/SignedOutHero.tsx` hides source explanation below `sm`. | Explain external applications in mobile-visible hero copy and validate comprehension. | S | no | no |
| H-02 | Done | `frontend/components/SearchFilters.tsx` form submits Enter, preserves query on category changes, updates public URL. | Verify touch and keyboard journeys on rendered home. | S | no | no |
| H-03 | Improve | `frontend/components/SignedInWelcome.tsx`, `SignedOutHero.tsx`, `RecentlyViewed.tsx` provide separate modes. | Add member deadline/search continuity and exercise account switching. | M | no | no |
| H-04 | Improve | `frontend/components/ForYouControl.tsx`, `backend/api/feed.py` offer personalization and deadline sort. | Define Following/verified rails and correct Latest's `last_seen_at` ordering. | M | no | no |
| H-05 | Improve | `backend/api/stats.py` counts open rows, returns `updated_at`; `frontend/components/StatsBar.tsx` says Updated daily. | Explain count populations and display actual latest observation timestamp. | S | no | no |
| H-06 | Improve | `frontend/components/OnboardingDialog.tsx` has steps, skip/back and final account save. | Persist incomplete drafts and account-backed country preferences. | M | no, reuse JSON | no |
| H-07 | Missing | `frontend/components/OnboardingDialog.tsx` teaches preferences, without a browse/apply/track tour. | Add dismissible accessible first-use explanation. | S | no | no |
| H-08 | Improve | `frontend/lib/recentlyViewed.ts` bounds/deduplicates 12 local entries; `RecentlyViewed.tsx` clears history. | Add per-item removal, disclosure and current closure reconciliation before account sync. | M | no initially | no |
| H-09 | Improve | `frontend/components/HeaderNav.tsx`, `MobileNav.tsx`, `MobileTabBar.tsx` provide keyboard-capable menus and active states. | Reconcile Arena/Competitions labels and verify two-interaction reachability with assistive technology. | S | no | no |

## 2. Search, filters and ranking

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| S-01 | Improve | `backend/api/search.py` uses FTS and trigram fallback; `api/filters.py` has role terms. | Benchmark aliases and company/title weighting before changing search expansion. | M | no initially | no |
| S-02 | Improve | `frontend/components/SearchFilters.tsx`, `backend/api/filters.py` support multiselect company/location and AND-composed groups. | Add source-backed eligibility facets and category multiselect without resetting URL state. | L | yes, eligibility | yes |
| S-03 | Improve | `backend/core/eligibility.py` handles source audience tags; `api/filters.py` excludes experienced-only audiences. | Design degree/batch evidence and explicit Unknown before eligible-only filtering. | L | yes | yes |
| S-04 | Improve | `backend/api/filters.py::location_scope_filters`, `frontend/components/LocationScope.tsx` distinguish domestic/foreign remote scope. | Add source-backed work-country/authorization fields and unknown restriction warnings. | L | yes | yes |
| S-05 | Improve | `backend/api/filters.py::role_signal_filters`, `frontend/lib/compensation.ts` preserve currency/period and undisclosed pay. | Benchmark mixed/base-variable pay and make supported conversions explicit. | M | no, existing meta | no |
| S-06 | Improve | `backend/api/filters.py::experience_filters('early')` negates senior regex without `NOT_SENIOR_TITLE_PATTERN` exception. | Preserve explicit graduate/intern exceptions in early-career mode, then benchmark description-based gaps. | M | no | no |
| S-07 | Improve | `backend/api/feed.py` orders recent by `last_seen_at`; `api/filters.py` has posted/deadline windows. | Sort documented posting freshness separately from observation freshness and label fallback dates. | M | no | no |
| S-08 | Improve | `frontend/lib/savedSearchParams.ts`, `backend/api/saved_searches.py`, `saved_searches` support portable saved filters. | Preserve currently unsupported sort/company filters with compatible validation. | M | no, existing params | no |
| S-09 | Improve | `backend/api/filters.py` supports closed/pay selection; `core/models.py` has no per-user hidden-listing state. | Define recoverable per-user exclusions and management UI. | M | yes | yes |
| S-10 | Improve | `backend/api/for_you.py` ranks skills/FTS; `frontend/components/SkillMatchCard.tsx` explains overlap only. | Return truthful feed ranking reasons and design reversible feedback persistence. | M | yes, feedback | yes |
| S-11 | Done | `backend/api/feed.py`, `search.py` have ID tie-breakers and bounded limits; `frontend/components/FeedViewControls.tsx` controls density. | Verify stable-snapshot pagination and mobile density. Concurrent crawl reordering remains outside stable-snapshot guarantee. | S | no | no |
| S-12 | Improve | `frontend/lib/listingResults.ts` stores failure as null; `components/FeedResults.tsx` silently substitutes initial data. | Show query-specific failure and retry while preserving filters and separating true zero results. | M | no | no |
| S-13 | Missing | `backend/tests/test_search.py` checks query contracts; no labeled ranking scorecard or zero-query analytics pipeline. | Establish anonymized benchmark and measurable regression thresholds. | M | no initially | no |

## 3. Cards, details and Apply

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| O-01 | Improve | `frontend/components/OpportunityCard.tsx` separates Save, wraps metadata, omits unknown pay/location. | Add explicit unknown metadata labels and inspect long real listings at 320px. | S | no | no |
| O-02 | Improve | `frontend/components/ListingFreshness.tsx` uses `postedAt ?? lastSeenAt` and renders unlabeled relative age. | Label Posted versus Last seen consistently, including absolute and hydrated dates. | S | no | no |
| O-03 | Improve | `frontend/app/opportunity/[slug]/page.tsx`, `lib/descriptionSections.ts` split requirements/eligibility and show source detail. | Add explicit missing values and source-backed documents/duration sections. | M | no initially | no |
| O-04 | Done | `backend/core/destination.py`, `frontend/lib/applyDestination.ts`, `components/ApplyLink.tsx` label host and separate click from confirmation. | Verify representative rendered destinations and free signed-in Apply. Preserve PR #132 gate. | S | no | no |
| O-05 | Improve | `frontend/components/SkillMatchCard.tsx` shows overlap; `backend/core/models.py::Bookmark` has no readiness checklist. | Separate hard eligibility from skill overlap and persist private checklists. | L | yes | yes |
| O-06 | Improve | `frontend/components/SaveButton.tsx`, `ReportIssueDialog.tsx` exist; guest Save only toasts through `BookmarksProvider.tsx`. | Preserve signed-out Save intent, then add reversible Hide and bounded Compare. | M | yes, Hide | yes |
| O-07 | Improve | `backend/pipeline/dedup.py` uses company/title/location; `ingest.py` preserves `opportunity_sources` and direct primary links. | Add explicit requisition/cohort identity guards against distinct-role merges. | M | yes, identity contract | yes |
| O-08 | Improve | `backend/pipeline/liveness.py` treats 503 as inconclusive; `api/filters.py::exclude_closed_competitions` retains 14-day grace. | Make confirmed-closed exclusion immediate for active search while preserving history/detail access. | M | no | no |
| O-09 | Not now | P2; `backend/core/models.py` stores latest opportunity fields without material-change events. | Revisit versioned material history after core accuracy work. | L | yes | yes |
| O-10 | Improve | `backend/api/reports.py` persists rate-limited `bug_reports`, emails founder, accepts four categories. | Add scam/duplicate/location/pay categories and severity/resolution handling. | M | yes, moderation | yes |

## 4. Authentication, profiles and privacy

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| A-01 | Improve | `frontend/lib/supabase/client.ts` uses PKCE; `backend/api/auth.py` verifies tokens and rejects mirror conflicts. | Exercise identity collisions and specify proof-based account linking with provider configuration. | M | no initially | yes |
| A-02 | Improve | `backend/api/account.py::update_account_me` patches owned fields; `api/schemas.py::AccountUpdate` validates name/college/year. | Add degree/major/academic-stage contract and validate existing JSON profile fields. | M | yes, education | yes |
| A-03 | Improve | `frontend/components/ResumeMatchPage.tsx`, `lib/taxonomy.ts`, `backend/api/account.py` persist skills/interests. | Normalize aliases and make role/industry/experience preferences affect workers consistently. | M | no, existing JSON | no |
| A-04 | Improve | `frontend/lib/profileCompleteness.ts` has shared percentage and actionable checklist; `components/account/ProfileSection.tsx` renders both. | Align percentage with useful preference checklist and verify reload stability. | S | no | no |
| A-05 | Improve | `frontend/components/ResumeMatchPage.tsx` saves free-text experience/notes in `users.exposure`. | Define repeatable private project/experience/certification records and ordering. | M | yes | yes |
| A-06 | Missing | `backend/core/models.py::User`, `frontend/components/account/ProfileSection.tsx` lack portfolio-link records and visibility controls. | Add validated private platform links before optional previews. | M | yes | yes |
| A-07 | Improve | `frontend/lib/savedResume.ts` validates PDF/5MB, upserts fixed path, signs 60s URLs; `backend/scripts/setup_resume_storage.sql` defines owner RLS. | Verify RLS and replacement/deletion failures, then reconcile derived skills/text retention with disclosed policy. | M | no initially | yes |
| A-08 | Not now | P2; `frontend/lib/savedResume.ts` intentionally stores one PDF per user. | Revisit named versions and application references after retention/storage design approval. | L | yes | yes |
| A-09 | Improve | `frontend/lib/fieldProfile.ts` syncs account interests; `lib/country.ts` stores country locally. | Persist country/work-mode/sort defaults with explicit URL precedence. | M | no, existing JSON | no |
| A-10 | Improve | `frontend/components/account/NotificationsSection.tsx` persists topic booleans; `backend/pipeline/notifications.py::wants` reads them. | Add timezone, quiet hours and global pause across workers. | M | no, JSON extension | no |
| A-11 | Improve | `frontend/components/account/SecuritySection.tsx` shows providers/password/global signout; `backend/api/auth.py` validates bearer sessions. | Add re-authentication for sensitive changes and exercise revocation against private endpoints. | M | no initially | yes |
| A-12 | Blocked | `backend/api/account.py::export_account` exports owned data; `frontend/components/account/SecuritySection.tsx` sends deletion requests by email. | Founder must approve retention/deletion exceptions and production deletion procedure before automation. | L | yes, lifecycle/audit | yes |
| A-13 | Done | `backend/api/account.py`, `bookmarks.py`, `saved_searches.py` scope private responses to authenticated user; storage SQL enforces owner paths. | Exercise full cross-user matrix, including private files and exports. | S | no | no |
| A-14 | Improve | `frontend/lib/authErrors.ts`, `lib/signOut.ts`, `app/reset-password/page.tsx` provide recovery paths. | Verify callback/session-expiry return intent and account switching in rendered journeys. | M | no | no |

## 5. Saves and applications

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| T-01 | Improve | `backend/api/bookmarks.py` uses composite key; `frontend/components/BookmarksProvider.tsx` serializes local toggles and rolls back. | Handle concurrent insert conflicts idempotently and add Undo before collections. | M | no initially | no |
| T-02 | Improve | `frontend/app/saved/page.tsx`, `backend/api/bookmarks.py`, `api/schemas.py` implement five manual persistent stages. | Add status-event history and agree additional tracker stages. | M | yes | yes |
| T-03 | Missing | `backend/core/models.py::Bookmark` contains status/created time only, without notes, interviews or resume references. | Add owned application details alongside existing bookmark contract. | M | yes | yes |
| T-04 | Improve | `frontend/components/ApplyLink.tsx` prompts after return; `BookmarksProvider.tsx::markApplied` requires explicit confirmation. | Add persistent Don't ask preference and explicit manual-action history. | M | yes, history | yes |
| T-05 | Improve | `frontend/components/AddToCalendar.tsx`, `lib/calendar.ts` export per-listing ICS; `backend/pipeline/notifications.py` sends reminders. | Add saved-deadline calendar with date-only semantics and source timezone. | M | yes, date semantics | yes |
| T-06 | Improve | `frontend/components/ApplyLink.tsx` reads tracker stages; opportunity detail shows closure warnings. | Expose existing application stage as a visible revisit warning. | S | no | no |
| T-07 | Improve | `frontend/app/saved/page.tsx` filters stages and edits one item at a time. | Add explicit selected-item bulk removal with per-item authorization and recoverable failures. | M | no initially | no |
| T-08 | Not now | P2; `backend/core/models.py::Bookmark` has no actor/event history. | Revisit after application history and export contracts exist. | M | yes | yes |
| T-09 | Improve | `backend/api/account.py::export_account` includes saves/searches/statuses as JSON; `frontend/lib/calendar.ts` exports one ICS. | Add safe CSV and combined calendar exports using existing owned queries. | M | no | no |

## 6. Notifications and company alerts

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| N-01 | Done | `backend/api/dream_companies.py` persists canonical IDs/domains with `can()` limits; `pipeline/notifications.py` matches future follows. | Verify follow/edit/unfollow delivery with current entitlements and real listing snapshots. | S | no | no |
| N-02 | Improve | `backend/api/saved_searches.py`, `pipeline/saved_search_alerts.py` implement daily matching, pause and watermark. | Add versioned retry-safe delivery and explicit cadence configuration. | M | yes, delivery identity | yes |
| N-03 | Improve | `backend/pipeline/notifications.py` checks sent rows before sending; `core/models.py::Notification` lacks unique event constraint. | Introduce transactional delivery identity/outbox and provider idempotency for concurrent/restarted workers. | M | yes | yes |
| N-04 | Improve | `backend/api/notifications.py` lists bounded inbox/unread count and marks all read. | Add paged individual read/unread/archive actions and cross-tab badge synchronization. | M | yes, archive | yes |
| N-05 | Improve | `backend/pipeline/notifications.py::send_daily_digests` checks UTC day, preferences and prior company alerts. | Add user-timezone scheduling, preview and visible last-send outcome. | M | no initially | no |
| N-06 | Improve | `backend/pipeline/notifications.py::send_company_alerts` gates timing via `can()`; `core/gating.py` checks subscription expiry. | Verify premium transitions and document crawl-to-alert latency from actual delivery evidence. | M | no | yes |
| N-07 | Improve | `backend/pipeline/notifications.py::send_closing_soon_alerts` queries active/deadline rows without `closed_at` or explicit-confidence guard. | Exclude confirmed closures/estimated dates, then add configurable reminder windows and change alerts. | M | yes, change events | yes |
| N-08 | Improve | `backend/api/notifications.py`, `core/unsubscribe.py` support signed topic unsubscribe and one-click POST. | Add provider suppression synchronization and explicit channel consent before new channels. | M | yes, consent | yes |
| N-09 | Improve | `backend/pipeline/company_alert_email.py`, `saved_search_alerts.py::_filter_summary` explain followed company/search criteria. | Include reproducible matched domain/location reasons in every opportunity notification. | S | no | no |
| N-10 | Improve | `backend/core/email_client.py` returns acceptance boolean; workers store sent/failed `notifications`. | Retain provider message IDs and bounded retry/dead-letter outcomes. | M | yes | yes |
| N-11 | Improve | `backend/pipeline/weekly_report.py` templates followed-company/deadline picks and honors opt-out/weekly sent guard. | Add self-reported tracker progress and ensure snapshot determinism with optional AI disabled. | M | no initially | no |

## 7. Resume analysis and matching

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| R-01 | Improve | `frontend/lib/pdfText.ts`, `resumeSkills.ts`, `components/ResumeMatchPage.tsx` parse locally, warn and permit skill edits. | Add layout/malformed-file corpus and a review step before autosaving extracted skills. | M | no | no |
| R-02 | Improve | `frontend/components/SkillMatchCard.tsx` explains deterministic overlap; `ResumeMatchPage.tsx` disables embedding matches. | Distinguish manual versus resume skill evidence and separate unknown hard requirements. Keep AI disabled. | M | no initially | no |
| R-03 | Improve | `backend/pipeline/skills.py`, `role_signals.py`, `frontend/lib/descriptionSections.ts` extract skills and requirement sections. | Preserve source snippets and distinguish required/preferred without generative inference. | M | yes, traceable evidence | yes |
| R-04 | Not now | P2; `frontend/lib/atsScore.ts` already offers deterministic readiness checks. | Validate source-grounded coaching demand before expanding suggestions. AI remains deferred. | M | no initially | yes |
| R-05 | Improve | `frontend/components/ResumeMatchPage.tsx`, `lib/savedResume.ts::mergeSkills` persist manual/resume provenance independently. | Explain which saved skills are manual and avoid attributing all overlap to the resume. | S | no | no |
| R-06 | Done | `backend/api/for_you.py` ranks terms without resume and falls back to scoped listings without terms. | Verify new-user results for representative interests and countries. | S | no | no |
| R-07 | Missing | `backend/api/for_you.py` accepts interests/skills only; `core/models.py` lacks reversible recommendation-feedback records. | Define minimal per-user feedback with reset before ranking integration. | M | yes | yes |
| R-08 | Not now | P2; `frontend/lib/savedResume.ts` stores one PDF and no comparison workspace. | Validate bounded comparison and resume-version use cases first. | L | yes | yes |

## 8. Ingestion, provenance and safety

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| Q-01 | Improve | `backend/core/models.py` defines raw/canonical/source links; `pipeline/ingest.py` replaces changed raw payloads. | Add parser-version/history evidence only after measured retention need and architect approval. | M | yes | yes |
| Q-02 | Improve | `backend/core/models.py::Opportunity` separates posted/first-seen/last-seen/deadline/closed; `api/feed.py` still sorts observation time. | Correct freshness ordering first. New checked/provenance dates require measured need under README 2026-11-04. | M | no first slice | yes |
| Q-03 | Improve | `backend/pipeline/location_country.py`, `company_resolution.py` normalize ISO country/company identity and retain location prose. | Benchmark ambiguous places and add manual correction queue. | M | yes, overrides | yes |
| Q-04 | Improve | `backend/core/models.py::Opportunity` has nullable remote/country/location; `api/filters.py` documents foreign-remote limitations. | Model permitted work countries separately from office country and remote arrangement. | L | yes | yes |
| Q-05 | Improve | `backend/pipeline/role_signals.py`, `core/pay_format.py`, `frontend/lib/compensation.ts` retain source pay units/unknowns. | Extend benchmark for variable/base pay and annotate conversion assumptions. | M | no, meta | no |
| Q-06 | Improve | `backend/pipeline/normalize.py` separates graduate jobs from internships; `api/filters.py` has seniority/title rules. | Benchmark category/experience evidence and confirm legacy new-grad backfill completion. | M | backfill | yes |
| Q-07 | Improve | `backend/pipeline/dedup.py` applies company/title/location similarity without requisition guard or merge/split history. | Preserve distinct requisitions/cohorts and record reversible merge decisions. | M | yes | yes |
| Q-08 | Improve | `backend/pipeline/liveness.py`, `expire.py`, `retirement.py` separate transient failures and guard full-inventory absence closures. | Document measured retirement window per source and add status/redirect edge cases. | M | no | no |
| Q-09 | Improve | `backend/core/destination.py`, `pipeline/company_logos.py`, `api/reports.py` provide host labels, logo evidence and reports. | Add safety-specific severity/snapshots and review/appeal workflow without equating logos with verified identity. | L | yes | yes |
| Q-10 | Improve | `backend/tests/test_greenhouse_adapter.py`, `backend/tests/test_unstop_adapter.py`, `backend/tests/test_role_signals.py`, `.github/workflows/ci.yml` already gate parser regressions. | Add labeled cross-field quality thresholds and routine real-output sampling. | M | no | no |
| Q-11 | Improve | `backend/crawlers/runner.py` records coverage in `crawl_runs`; `scripts/report_crawl_staleness.py` alarms after 48h. | Surface existing source metrics and distinguish stale contact from incomplete coverage. | M | no initially | no |
| Q-12 | Improve | `backend/crawlers/common.py` supplies UA/backoff; `runner.py` filters `sources.legal_status`; `docs/04-crawler-system.md` governs access. | Audit each adapter's robots/terms implementation and document allowed method/owner. | M | no | yes |
| Q-13 | Improve | `backend/api/reports.py`, `core/models.py::BugReport` store requests/status without decision/reviewer/override history. | Agree correction ownership and add expiring audited overrides. | M | yes | yes |
| Q-14 | Improve | `frontend/app/about/page.tsx`, `faq/page.tsx`, opportunity detail explain link-out and reporting. | Consolidate source methodology and distinguish observation from verified openness. | S | no | no |

## 9. Companies and collections

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| C-01 | Improve | `backend/api/company.py`, `frontend/components/CompanyOpportunities.tsx` show counts, domain, listings and Follow. | Reconcile closed-grace counts and add sourced sector/careers metadata. | M | yes, metadata | yes |
| C-02 | Improve | `backend/pipeline/company_resolution.py` exact-normalizes names; `core/models.py::DreamCompany` references stable company ID. | Add controlled aliases and merge/split history with follow remapping. | M | yes | yes |
| C-03 | Improve | `backend/pipeline/notifications.py::_dream_company_opportunities` queries followed-company arrivals; no Following page exists. | Reuse matching rules for a private Following feed, then add material-change history. | M | yes, change history | yes |
| C-04 | Improve | `backend/api/dream_companies.py` supports flat canonical follows with domain preferences and quotas. | Define named collections and downgrade-safe alert priority. | M | yes | yes |
| C-05 | Not now | P2; `backend/api/company.py` has company counts/search without industry browsing or student-footprint score. | Validate company-discovery demand before authoring sector taxonomy. | M | yes | yes |

## 10. Competitions, research and programmes

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| K-01 | Improve | `backend/pipeline/competition_signals.py`, `frontend/components/CompetitionsAdvancedFilters.tsx`; separate `programmes`/`programme_editions` exist. | Add typed source-backed fields/unknown labels while preserving the binding registry model. | M | no initially | no |
| K-02 | Improve | `backend/pipeline/competition_signals.py`, `frontend/lib/competition.ts` expose prizes, teams, mode and deadline metadata. | Distinguish registration/submission dates and display source-derived eligibility. | M | yes, date semantics | yes |
| K-03 | Improve | `backend/api/programmes.py`, `backend/data/programmes.json`, `frontend/app/research/page.tsx` supply research registry/eligibility prose. | Architect authors verified academic requirements before adding degree facets. | M | yes, structured fields | yes |
| K-04 | Improve | `frontend/app/scholarships/page.tsx` combines scholarship listings/registry; programme eligibility is nullable prose. | Structure verified scholarship requirements and explicit unknowns without sensitive financial inference. | M | yes | yes |
| K-05 | Improve | `backend/core/models.py::ProgrammeEdition`, `frontend/components/ProgrammeCard.tsx` distinguish confirmed editions from expected windows. | Obtain authored fee/stage/duration evidence and deliberate edition verification. | M | yes, extra fields | yes |
| K-06 | Improve | `frontend/lib/calendar.ts` exports single deadline; `components/ProgrammeAlmanac.tsx` charts programme windows. | Add personal cross-category calendar from confirmed saved deadlines. | M | no initially | no |
| K-07 | Not now | P3 competition communities require validation and moderation; no team-discovery routes in `backend/api/main.py`. | Founder validates demand and moderation/privacy operating model first. | L | yes | yes |

## 11. Pricing and billing

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| B-01 | Improve | `backend/api/plans.py`, `core/gating.py`, `frontend/components/PricingPlans.tsx`, `lib/planFeatures.ts` share entitlement data and curated copy. | Reconcile renewal/tax/refund copy and every advertised feature with provider-backed cases. | M | no | yes |
| B-02 | Done | Public `backend/api/feed.py`, `search.py`, opportunity routes and free `frontend/components/ApplyLink.tsx` require no purchase. | Preserve Apply sign-in per README 2026-11-02/PR #132. Compare around 2026-11-16 without reopening now. | S | no | no |
| B-03 | Improve | `backend/api/payments.py` verifies signatures, guards replay/order, locks upgrades; `tests/test_payments_webhook.py` covers callbacks. | Add checkout retry identity/refund reconciliation and verify provider failure cases. | M | yes, payment identity | yes |
| B-04 | Improve | `backend/api/payments.py` creates recurring subscriptions and annual-switch access; `api/account.py` schedules cancellation. | Document each sale path's renewal semantics and verify expiry/cancellation UI against provider state. | M | no | yes |
| B-05 | Missing | `frontend/components/account/SubscriptionSection.tsx` shows plan state; `backend/api/main.py` exposes no billing-history/receipt route. | Define owner-only provider-backed transaction history and invoice/tax responsibility. | M | yes, billing records | yes |
| B-06 | Improve | `backend/api/payments.py` locks plan transitions; `dream_companies.py` preserves existing follows and limits additions. | Define excess-follow alert priority after downgrade and display paused rules clearly. | M | yes, pause policy | yes |
| B-07 | Improve | `frontend/components/FollowCompanyButton.tsx`, `PricingPlans.tsx` explain limits and upgrade entry points. | Add clearly labeled real-format alert/report previews using running benefits only. | S | no | no |
| B-08 | Improve | `backend/core/referral.py::record_referral` locks set-once claims, rejects self-referral and grants bounded comp access. | Define qualified conversion/fraud reversal policy before additional abuse controls. | M | yes, reward audit | yes |
| B-09 | Blocked | `frontend/app/refunds/page.tsx`, `contact/page.tsx`, `faq/page.tsx` offer policy/contact, without ticket tracking. | Founder must define billing support ownership, response targets and refund escalation before tracked tickets ship. | M | yes, tickets | yes |

## 12. Mobile, accessibility and SEO

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| U-01 | Improve | `frontend/components/OpportunityCard.tsx`, `MobileTabBar.tsx`, `FacetPicker.tsx` use wrapping, touch targets and safe-area inset. | Render 320–430px journeys with keyboard open and correct any measured clipping. | M | no | no |
| U-02 | Improve | `frontend/app/layout.tsx` has skip link; `components/ui/dialog.tsx`, `sheet.tsx` provide modal primitives and focus behavior. | Run keyboard/screen-reader/a11y acceptance and repair observed failures. | M | no | no |
| U-03 | Improve | `frontend/app/globals.css`, `components/RelativeDeadline.tsx`, `SaveButton.tsx` define colors and textual/icon states. | Measure current v2 contrast and grayscale states. Earlier theme scores cannot certify this version. | M | no | no |
| U-04 | Improve | `frontend/app/saved/page.tsx` retries load errors; `components/FeedResults.tsx` silently falls back on search failure. | Extend explicit retry/offline handling across listing routes and preserve form drafts. | M | no | no |
| U-05 | Improve | `frontend/components/SearchFilters.tsx` resyncs from URLs; `lib/listingResults.ts` retains bounded per-route query results. | Verify Back/Forward scroll and list identity across detail visits. | S | no | no |
| U-06 | Improve | `backend/api/middleware.py` caches public reads; `frontend/app/layout.tsx` uses fonts and Analytics without vitals reporting. | Add privacy-safe real-user LCP/INP/CLS collection and measure target segments. | M | no initially | yes |
| U-07 | Improve | `frontend/components/SearchFilters.tsx` announces pending state; `ListingFreshness.tsx` loses `<time>` after hydration. | Announce settled counts and expose semantic labeled dates without noisy regions. | S | no | no |
| U-08 | Improve | `frontend/app/opportunity/[slug]/page.tsx::buildJobPostingJsonLd` filters job types/closure but falls back datePosted to first_seen_at. | Require source-backed publication dates for JobPosting and verify canonical/indexation output. | M | no | no |
| U-09 | Not now | P2; `frontend/lib/date.ts`, `compensation.ts` already format dates and original currency. | Validate international date/time clarity before broader localization. | M | no initially | no |
| U-10 | Not now | P2; `frontend/app/manifest.ts` and icons exist, without an offline/private-cache service-worker contract. | Validate install/offline demand and partitioned caching before adding push. | M | no initially | yes |

## 13. Security and compliance

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| SEC-01 | Improve | `backend/api/auth.py`, owned resource queries and `tests/test_bookmarks.py`, `test_account.py` enforce private access. | Complete endpoint-by-endpoint cross-user negative matrix, including files and billing. | M | no | no |
| SEC-02 | Improve | `backend/scripts/setup_resume_storage.sql`, `frontend/lib/savedResume.ts` enforce private PDF limits and signed retrieval. | Verify active storage policies and define effective derived-data retention/deletion checks. | M | no initially | yes |
| SEC-03 | Improve | `frontend/lib/descriptionBlocks.ts` reconstructs description markup; PKCE/bearer auth exists; `frontend/next.config.ts` has no explicit security headers. | Audit URL protocols and deploy practical measured CSP/header controls with regression payloads. | M | no | no |
| SEC-04 | Improve | `backend/api/middleware.py`, `reports.py`, `core/ratelimit.py` bound reads/report writes; auth/referral use separate paths. | Audit limits on uncovered abuse surfaces and provider signup controls. | M | no initially | yes |
| SEC-05 | Blocked | `users.notification_prefs`, `backend/core/unsubscribe.py` implement preference opt-out without timestamped purpose/channel consent ledger. | Founder must approve consent purposes and retention/legal requirements before collecting auditable consent. | M | yes | yes |
| SEC-06 | Improve | `backend/core/config.py` reads secret configuration; `api/main.py` exposes no scoped admin/moderation role system. | Define least-privilege operator roles and audited privileged actions. | L | yes | yes |
| SEC-07 | Improve | `.github/workflows/backup.yml`, `backend/scripts/backup_db.py`, `restore_from_backup.py`, `infra/db/RUNBOOK.md` define backups/restore. | Founder schedules restore drill and approves deletion-aware restore/RPO/RTO policy, including resume objects. | M | no initially | yes |

## 14. Operations and quality assurance

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| OPS-01 | Improve | `backend/crawlers/runner.py`, `scripts/report_crawl_staleness.py`, `crawl_runs` record coverage/outcomes and alarm staleness. | Build restricted source dashboard over existing metrics and prove outage alarm routing. | M | no initially | no |
| OPS-02 | Improve | `backend/api/reports.py` stores reports and notifies founder; `bug_reports` has open status only. | Add severity, reviewer/decision history and reversible quarantine after ownership decision. | M | yes | yes |
| OPS-03 | Improve | `backend/api/opportunity.py`, `core/models.py::OpportunityActionCount` record anonymous daily Apply/gate totals. | Add aggregate save/manual-apply counts within README 2026-11-03 privacy bounds. User-linked click funnels require amendment. | M | yes, event/count contract | yes |
| OPS-04 | Missing | `backend/tests/test_search.py`, `test_for_you.py` cover contracts without product relevance scorecard/rollback thresholds. | Establish privacy-safe search/recommendation benchmark and quality release thresholds. | M | no initially | no |
| OPS-05 | Improve | `backend/core/models.py::Notification`, `pipeline/notifications.py` record accepted/failed sends and skipped counts. | Correlate eligible events and provider outcomes without treating acceptance as delivery. | M | yes, delivery identity | yes |
| OPS-06 | Improve | `backend/api/middleware.py` returns DB/total timing; workers log exceptions and run statistics. | Add privacy-safe request/worker correlation IDs and actionable failure alerts. | M | no initially | no |
| OPS-07 | Improve | `sources.enabled/legal_status`, payment UI flag and `.github/workflows/enrich.yml` provide existing kill switches. | Define server-evaluated per-feature rollout flags and documented rollback paths. | M | no initially | no |
| OPS-08 | Improve | `.github/workflows/ci.yml` runs disposable-DB backend suite, frontend lint/types/build and ISR guard. | Add browser E2E critical journeys and reproducible failure artifacts. | M | no | no |
| OPS-09 | Improve | `frontend/components/ReportIssueDialog.tsx`, `backend/api/reports.py` already support durable feedback. | Add feature/severity triage and a public changelog free of private report details. | M | yes, triage | yes |
| OPS-10 | Improve | `backend/core/ai_budget.py`, `ai_client.py`, `cache.py`, `.github/workflows/notifications-digest.yml` cap/batch costly work. | Add measured email/source/unit-cost reporting and sustained budget alarms while AI stays deferred. | M | no initially | yes |

## 15. Conditional future capabilities

| ID | Status | Evidence (file paths, routes, tables) | Smallest safe next step | Size S/M/L | Migration? | Founder? |
|---|---|---|---|---|---|---|
| FUT-01 | Ruled out | `CLAUDE.md` all-AI deferral and `docs/README.md` 2026-11-03 founder ruling override optional P2 AI editor. | Obtain founder reversal and architect amendment before AI assistance. | L | no initially | yes |
| FUT-02 | Not now | P2; `frontend/app/saved/page.tsx` has stage counts, without career-progress analytics. | Validate repeated tracker use before progress dashboard. | M | yes, history | yes |
| FUT-03 | Not now | P2; `docs/README.md` 2026-07-31 excludes learning resources from registry scope. | Validate source-backed preparation scope and obtain amendment if introducing excluded resource content. | M | no initially | yes |
| FUT-04 | Not now | P3; `users.college` exists without institutional membership/community services. | Validate opt-in institution use case and privacy contract first. | L | yes | yes |
| FUT-05 | Not now | P3; `backend/api/main.py` contains no team messaging/discovery surface. | Validate demand and moderation capacity before opt-in team design. | L | yes | yes |
| FUT-06 | Not now | P3 conditional; ATS crawler adapters read public listings, without authorized application-status partnership APIs. | Founder obtains authorized partnership scope and consent contract first. | L | yes | yes |
| FUT-07 | Not now | P3; `frontend/app/manifest.ts` provides install metadata, without native application projects. | Validate mobile retention/PWA limitations and founder business case. | L | no initially | yes |

## Proposed Batch 1

Six Release A/P0 items, grouped into three PR-sized batches. All are `Improve`, S/M, with no schema migration, backfill or founder action for these slices. Verification below is future acceptance work. This inventory did not execute it. The three batches have disjoint implementation files.

### PR 1 — Public orientation and count context

- **H-01 · S.** Touch `frontend/components/SignedOutHero.tsx`. Keep a concise source-first/application-destination explanation visible at mobile widths and remove the unsupported never-miss promise. Verify a rendered signed-out home at 320px and desktop, public Enter search, and first-viewport comprehension. Risk is hero height pushing search below the fold.
- **H-05 · S.** Touch `frontend/components/StatsBar.tsx`. Explain open student-facing canonical listings, distinct companies and represented sources. Render existing `stats.updated_at` as the latest listing observation with an exact accessible date and unknown fallback. Verify against an architect-provided real `/stats` snapshot and rendered zero/null/positive cases. Risk is presenting one latest observation as proof every source is fresh, so wording must state its limited meaning.

### PR 2 — Search relevance and recoverable failure

- **S-06 · M.** Touch `backend/api/filters.py` and existing `backend/tests/test_feed_filters.py`. In `experience_filters('early')`, retain titles explicitly identifying internships/new graduates when the broad senior regex also matches. Reuse `NEW_GRAD_TITLE_PATTERN` and explicit intern tokens while keeping unqualified senior roles excluded. Verify on an architect-provided, labeled real-title sample covering senior graduates, technical staff new grads, actual senior jobs and ordinary internships. Record inclusion/exclusion counts. Risk is false-positive student results, so benchmark the exact changed subset.
- **S-12 · M.** Touch `frontend/lib/listingResults.ts`, `frontend/components/FeedResults.tsx`, `frontend/components/OpportunityLandingResults.tsx` and `frontend/components/CompetitionsResults.tsx`. Expose a failed-request state and bounded explicit retry for the current route/query. Keep query/filter controls, distinguish zero matches, and clearly identify any retained fallback rows. Verify rendered searches backed by real listing snapshots, then intercept 429/500/offline responses and retry successfully without changing URL filters. Risk is store/remount races across listing routes, so exercise rapid query changes and Back navigation.

### PR 3 — Card metadata clarity

- **O-01 · S.** Touch `frontend/components/OpportunityCard.tsx`. For job/internship cards, render `Pay not disclosed` and `Location not stated` when their source-backed fields are absent. Preserve actual pay units and explicit unpaid text. Verify long real titles/locations, remote roles with unknown country, and stated/unstated/unpaid samples at 320px and desktop. Risk is extra card height and metadata clutter.
- **O-02 · S.** Touch `frontend/components/ListingFreshness.tsx` and its caller `frontend/components/OpportunityCard.tsx`. Label dates as `Posted` only with `posted_at`, otherwise `Last seen`. Retain semantic `<time>` and exact absolute context before/after hydration, including New badges. Verify a rendered real old-posted/recently-seen listing and a missing-posted listing under an old ISR snapshot. Risk is hydration mismatch or untruthful verification claims, so Last seen must describe observation only.

## Spec claims that are wrong for this codebase

Most proposed contracts are explicitly conceptual and many behaviors are marked VERIFY. These corrections concern implementation baselines and interpretations.

- S-01's exact-substring rationale does not describe current search. `/search` already uses weighted Postgres FTS and trigram fallback. Alias quality still needs benchmarking (`backend/api/search.py`, `backend/migrations/versions/bf2369a490a6_phase_1_core_schema.py`).
- Appendix A's programme/fellowship-inside-Opportunity model differs from the binding registry split. Recurring research/scholarship programmes have stable registry rows and separately verified editions alongside crawled listings (`docs/README.md` 2026-07-31, `backend/core/models.py`).
- R-02's observed score framing must distinguish the running skill-overlap percentage from disabled embedding-based resume ranking. The current percentage compares detected listing skills with saved skills, including manual additions (`frontend/components/SkillMatchCard.tsx`, `frontend/components/ResumeMatchPage.tsx`).
- B-02's source-access protection permits free signed-in applications. Any interpretation requiring guest Apply clicks through conflicts with PR #132's binding sign-in experiment, with comparison due around 2026-11-16 (`docs/README.md` 2026-11-02, `frontend/components/ApplyLink.tsx`).

## Unverified boundaries

Runtime correctness, production row/backfill coverage, active Supabase policies/provider settings, payment reconciliation, email delivery, current accessibility/vitals and cross-device persistence require later authorized verification. Code evidence establishes implemented paths and specific gaps, without certifying those external states. Batch 1 leaves the broader schema-dependent requirements attached to their inventory rows.
