# ASPIROVA — COMPLETE FEATURE ADDITION & IMPROVEMENT SPECIFICATION

Developer-ready product requirements and implementation roadmap  
Website: https://www.aspirova.org  
Version: 1.0  
Audit date: 10 November 2026  
Audience: Founder/product owner, Claude (architect/reviewer), Codex (implementation), QA tester  
Scope: Public discovery, onboarding, search, listings, profile, saved items, applications, alerts, resume matching, company pages, competitions/research/scholarships, paid plans, trust, accessibility, operations, security, analytics.

> Evidence discipline: This is a feature specification, not a claim that all listed features are missing or broken. OBSERVED means visible in the inspected logged-in homepage/browser context; DOCUMENTED means described on Aspirova's public FAQ/About pages; VERIFY means the end-to-end behavior could not be validated; NEW is a proposed capability; IMPROVE means an observed or documented capability should be enhanced. Source links appear in Appendix D. No authenticated payment, profile-save, email-delivery, backend, or cross-device transaction tests were executed.

## 0. Executive decision brief

Aspirova's strongest position is source-first, personalized discovery of opportunities: it indexes public career and opportunity sources and sends applicants to the original application. Its FAQ states that browsing/search and the daily digest are free, while Pro adds instant alerts, a weekly report, and capacity to track more companies. The FAQ also advertises saving listings and tracking applications. Its homepage visibly provides category navigation, For You/Latest feeds, search, geographical preferences, cards, companies, saved and matches links, notifications and account entry points.

The roadmap must therefore prioritize accuracy, targeting, trustworthy sources, usable personal workspaces, and notification quality, while preserving existing functionality. Do not build a native employer application system simply because competitors have one; Aspirova explicitly describes itself as an aggregator and states that applications happen on the original sites.

### Priority scheme

- P0 — Essential: Trust, correctness, core journeys, security, accessibility, destructive/payment workflows and high-impact search accuracy. Deliver first.
- P1 — High: Retention, saved-search alerts, profile matching, application tracking refinement, company-follow experience, stronger category data.
- P2 — Differentiator: Advanced comparisons, resume coaching, collaboration, analytics and optional channels.
- P3 — Future/conditional: Employer integrations, institutions, communities, native apps. Only after product-market and legal/operational validation.

### Status and scope rules for implementation

- Inventory before editing. Search actual routes, components, tables, API contracts, scheduled workers, billing entitlements and tests. An item marked VERIFY is not authorization to rewrite an existing feature.
- Never conflate data concepts: originally_posted_at, first_seen_at, source_updated_at, last_verified_at, deadline_at and closed_at serve different purposes.
- Never infer that an external application succeeded from a click or redirect; only a manual user action or an authorized source can confirm it.
- Never call an employer verified only because a recognizable name/logo appears. Separately represent source URL validity, organization identity verification and open/closed status.
- All optional fields are nullable, including compensation, year eligibility, location restriction, duration and deadline. Unknown ≠ no restriction, unpaid or zero.
- Maintain free access to listing discovery, original source links, safety information, and abuse reporting. Don't fabricate scarcity, hiring probability or candidate eligibility.
- Keep migrations reversible, backfill carefully, deploy changes behind flags when risky, and provide regression tests for every high-impact workflow.

### Minimum viable release sequence

Release A (P0): source integrity, original-vs-crawl timestamps, location/remote distinctions, relevance filters, accessible search, account/profile persistence, notification deduplication, billing/account safety.  
Release B (P1): saved searches, dream-company subscriptions, structured application workspace, deadlines/calendar, explainable matches, polished company pages.  
Release C (P2): advanced resume support, comparisons, reports, category-specific discovery, progress analytics, PWA and optional channels.  
Release D (P3): institutional/community/employer workflows only after explicit business validation.

## 1. Homepage, landing experience, navigation and onboarding

### H-01 — Clear public-facing value proposition

Priority / status: P0 · IMPROVE  
Why: First-time visitors must understand whether this is a job board, an application service or a search aggregator before trusting it.  
How: Make the hero answer "What is indexed?", "Where does Apply go?", "How fresh are listings?" in concise language. Include category shortcuts and one primary search CTA. Avoid language implying employer partnerships or guaranteed jobs. Keep an informative public view distinct from the logged-in almanac/dashboard.  
Done when: Unauthenticated visitors can search without registration; first viewport communicates the source-first model on desktop/mobile; usability test participants can describe the product accurately.

### H-02 — Search-first hero and category entry points

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Users commonly arrive with a role, company or category in mind.  
How: Put a prominent query field and accessible category chips (Internships, Jobs, Competitions, Research, Scholarships, Programmes) above or near the feed. Preserve query text when switching categories. Provide useful placeholders without restricting input.  
Done when: Keyboard and touch search both work; search submits on Enter; category selection affects results and URL; no login wall appears solely for search.

### H-03 — Differentiated logged-in and visitor homepages

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Returning users need continuity; new visitors need orientation rather than personal account metrics.  
How: For members, show recently viewed, saved-search activity, relevant deadlines and top matches. For visitors, show editorially selected live categories and an explanation of the pipeline. Avoid hydration flashes of member-only content.  
Done when: Each mode has an appropriate CTA; member data never leaks into anonymous cache; account switching updates content correctly.

### H-04 — New, relevant, and closing-soon rails

Priority / status: P1 · IMPROVE  
Why: One large mixed feed makes urgent opportunities hard to locate.  
How: Offer separate sections or tabs for For You, Latest, Following, Closing Soon and Recently Verified. Use per-user criteria for For You, original dates for Latest, strict source-backed deadlines for Closing Soon. Provide source explanations for labels.  
Done when: Each rail uses documented ranking rules; empty rails have meaningful fallback; unknown deadlines do not appear as "closing soon".

### H-05 — Explain homepage counts and freshness

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Raw listing and company counts can be misleading if they include stale or ineligible records.  
How: Define and expose whether counts mean "currently open/last verified", total indexed, unique organizations and unique sources. Use server-calculated counts and an accessible last-refresh indicator; don't hardcode marketing numbers.  
Done when: Counts reconcile with filtered database queries and update without misleading zero/flash states.

### H-06 — Progressive onboarding (skippable)

Priority / status: P1 · VERIFY  
Why: Long forms reduce early activation; blank profiles produce weak recommendations.  
How: Request interests, preferred countries/locations, opportunity categories and academic stage first. Offer graduation year and company-follow selection next, with resume optional. Save partial progress transactionally. Provide Skip/Back/Edit.  
Done when: Users can exit and return without losing completed preferences; no optional field blocks browsing or applying externally.

### H-07 — Transparent first-use education

Priority / status: P1 · NEW  
Why: Users may think save, apply and track all happen on Aspirova.  
How: Show a dismissible "Browse → Check eligibility → Apply at original source → Track" tour. Explain how recommendations, freshness badges and Pro alerts operate; link to FAQ and source policy.  
Done when: Tour displays only when useful, respects dismissal, is keyboard accessible and makes no false application claims.

### H-08 — Recently viewed and continue browsing

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Users often return to a previously opened position.  
How: Store bounded recent-view history with privacy controls, deduplicate by canonical opportunity ID, offer Clear/Remove, and exclude deleted/expired details unless labeled. Prefer account-backed synchronization for signed-in users and browser-local data for guests only with disclosure.  
Done when: View history is accurate across visits; Clear is effective; stale entries show correct closure state.

### H-09 — Navigation clarity and mobile IA

Priority / status: P0 · OBSERVED / VERIFY  
Why: Opportunity categories, Saved, Matches, Pricing and account controls can become crowded.  
How: Audit top nav, hamburger menu and bottom navigation. Use consistent labels, active states, focus handling and back navigation. Ensure no important action is hidden behind hover-only controls.  
Done when: Every primary route is reachable within two interactions on mobile and desktop, including by keyboard/screen reader.

## 2. Search, filters, sorting and recommendation quality

### S-01 — Role/skill/company search with typo tolerance

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Exact substring search misses role aliases and commonly misspelled technologies.  
How: Normalize tokens, aliases (SDE/software engineer, ML/machine learning), case and punctuation; add lexical search first, optional semantic rerank later. Preserve exact company and title boosts. Log anonymized zero-result queries.  
Done when: Benchmark queries return the correct category at high rank; typo tests pass; irrelevant semantic expansion is constrained.

### S-02 — Multiselect, composable filters

Priority / status: P0 · OBSERVED / VERIFY  
Why: Students need combinations such as remote + paid + summer + second/third year.  
How: Support category, role, company, countries/cities, work mode, pay, experience, duration, graduation year and freshness. Apply AND across groups, OR within a group; show selected chips and one-click Clear All.  
Done when: Query params, displayed counts and results stay in sync; browser Back restores filters; no accidental reset on page changes.

### S-03 — Graduation-year and degree eligibility filter

Priority / status: P0 · NEW / VERIFY  
Why: Many internships have explicit batch/year and program restrictions.  
How: Extract source-backed requirements into structured fields with provenance and confidence, map to profile years/degrees, and offer Eligible / Possible / Not eligible / Unknown. Do not treat "not specified" as universal eligibility.  
Done when: Explicit mismatches are correctly excluded in eligible-only mode and the source text explaining restrictions is accessible.

### S-04 — Work authorization, citizenship and geographic scope

Priority / status: P0 · NEW  
Why: "Remote" does not necessarily mean a student in India can apply globally.  
How: Separate work arrangement from permitted work countries, citizenship, visa sponsorship and relocation requirements. Prefer source quotes and Unknown status to uncertain geography guesses.  
Done when: Remote-US-only roles cannot appear as globally eligible without warning; users can filter by work authorization requirements.

### S-05 — Compensation and stipend filters with units

Priority / status: P0 · IMPROVE  
Why: "Paid" without a value, hourly pay, monthly stipend and annual compensation are not interchangeable.  
How: Model amount min/max, currency, period, total-vs-variable, unpaid and undisclosed separately. Convert units only when defensible and always retain original values; mark conversion estimates.  
Done when: Pay filters never equate unspecified with zero; cards display correct unit and currency; mixed-pay roles remain interpretable.

### S-06 — Experience and seniority gating

Priority / status: P0 · IMPROVE  
Why: Student internship searches should not fill with senior positions.  
How: Classify internships, apprenticeships, early-career/graduate, mid, senior and unknown from titles plus description and source fields; give users an easy "Student/fresher roles only" toggle.  
Done when: A curated gold dataset shows senior roles excluded from student-only mode without hiding genuine graduate jobs.

### S-07 — Temporal filters and deadline sorting

Priority / status: P0 · IMPROVE  
Why: Urgency matters, but using crawl time as posted time is misleading.  
How: Distinguish posting freshness from ingestion freshness; sort deadlines with timezone-safe UTC storage and localized display. Filter Today/3d/7d/30d and Closing Soon. Preserve unknown as a separate bucket.  
Done when: A record re-crawled today but posted last month does not appear as newly posted; deadline-boundary tests pass.

### S-08 — Search presets and shareable URLs

Priority / status: P1 · NEW / VERIFY  
Why: Repeated searches should not require re-entering the same filters.  
How: Encode non-sensitive filters and sort in stable URLs; add Save Search with a name and notification toggle. Ensure encoding tolerates Unicode, multiple values and URL length constraints.  
Done when: Shared URLs reproduce public filters; saved searches work across devices; no private resume/profile data leaks into URLs.

### S-09 — Negative and exclusion filters

Priority / status: P1 · NEW  
Why: Users waste time seeing already applied, saved-rejected or irrelevant records.  
How: Add Hide applied, Hide expired, Hide unpaid, Exclude keyword/company and Not interested. Store per-user exclusions with undo and sensible expiration/relevance rules.  
Done when: Hidden records stay hidden after refresh but can be recovered from a management page.

### S-10 — Ranking transparency and feedback

Priority / status: P1 · OBSERVED / IMPROVE  
Why: For You feeds feel arbitrary when match signals are invisible.  
How: Surface 2–3 truthful ranking reasons (follows company, matches role, chosen location). Collect Show less / Not relevant / Save signals, with safeguards against cold-start overfitting.  
Done when: Every personalized ranking is explainable without exposing sensitive profile fields to third parties; feedback changes later ranking.

### S-11 — Fast, stable pagination and list density controls

Priority / status: P0 · OBSERVED / VERIFY  
Why: Large result sets require stable ordering, fast navigation and predictable scroll behavior.  
How: Prefer cursor pagination over deep offset where practical; enforce deterministic tie-breakers; preserve selected grid columns/rows only where responsive. Virtualize cautiously to protect SEO and accessibility.  
Done when: No duplicates/skips between pages in stable snapshots; no unbounded full-database download; mobile density remains usable.

### S-12 — Search empty, loading and error states

Priority / status: P0 · VERIFY  
Why: Empty results or API delays must not resemble a broken site.  
How: Show selected filter context, suggestions to relax constraints, retry actions, skeleton states and offline failure messaging. Cancel stale requests on fast input changes.  
Done when: Simulated 0-result, 429, 500, timeout and connection-loss cases remain understandable and actionable.

### S-13 — Query analytics and relevance evaluation

Priority / status: P1 · NEW  
Why: Relevance cannot be improved reliably from intuition alone.  
How: Maintain a labeled benchmark of representative India/global student searches; measure NDCG/precision@k and zero-results, segregated by category. Instrument privacy-respecting search events and A/B tests.  
Done when: Each search ranking change has pre/post metrics and regression thresholds.

## 3. Opportunity cards, detail pages and external application handoff

### O-01 — Consistent, compact card information hierarchy

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Users decide in seconds whether a listing is useful.  
How: Prioritize title, employer, role type, country/city/work mode, pay, deadline, posting freshness and source; use explicit Unknown or Not disclosed. Make entire card readable while leaving Save as its own accessible control.  
Done when: Key fields remain visible without overflow at small screen widths; screen readers distinguish card navigation and Save.

### O-02 — Clear metadata labels for posted/verified dates

Priority / status: P0 · OBSERVED / IMPROVE  
Why: A "today" badge can mistakenly describe a newly crawled old listing.  
How: Display "Posted" only from source-supported publication dates; otherwise "First seen" or "Checked" with exact hover/detail text. Keep ISO timestamps in storage and locale/timezone formatting in UI.  
Done when: Fixture with posted=Sept, checked=Nov shows the correct semantics everywhere.

### O-03 — Structured opportunity detail layout

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Unstructured text hides eligibility and important application requirements.  
How: Organize original summary, responsibilities, eligibility, required/preferred skills, compensation, duration, deadline, location, employer, documents and application process. Preserve a source-content section for fidelity; never invent missing values.  
Done when: Fields reconcile with original source and missing data is indicated clearly without implying eligibility.

### O-04 — Source-first Apply action with clear destination

Priority / status: P0 · DOCUMENTED / IMPROVE  
Why: Aspirova explicitly redirects applicants; unclear buttons create false expectations.  
How: Label button "Apply on [Company/Source]"; open the verified canonical URL safely; show source domain; use redirect only if it does not degrade trust. Record click separately from application status.  
Done when: Cross-domain link targets are correct, do not expose access tokens, and never mark Applied automatically.

### O-05 — Eligibility and application-readiness panel

Priority / status: P1 · NEW  
Why: Users waste effort opening roles with unmet hard requirements or missing documents.  
How: Show source-backed hard requirements, unknowns and a checklist of resume, cover letter, portfolio, transcript, assessment and deadline. Pull from listing source, then let users edit checklist privately.  
Done when: Unknown eligibility is not rendered "eligible"; checklist is persisted without modifying source facts.

### O-06 — Save, hide, compare and report actions

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Each listing should support multiple user intentions beyond an Apply click.  
How: Expose Save/Unsave, Hide/Undo, Compare and Report as distinct accessible actions. Handle signed-out save by preserving intent through login.  
Done when: All actions have confirmation/undo where appropriate and don't trigger card navigation inadvertently.

### O-07 — Duplicate role detection and canonical listing

Priority / status: P0 · IMPROVE  
Why: The same role may be present through ATS, career pages and third-party boards.  
How: Use normalized employer, requisition ID, title, location and canonical URL; maintain a dedup cluster with provenance rather than deleting source records. Prefer official employer link as primary when valid.  
Done when: Duplicate fixtures consolidate visibly without merging distinct internship cohorts or locations.

### O-08 — Closed/expired/uncertain states

Priority / status: P0 · IMPROVE  
Why: Broken application links quickly undermine trust.  
How: Apply bounded link revalidation, ATS status where allowed, stale thresholds, soft close/retire status, "Report closed" and manual review; do not infer closed solely from a single temporary network error.  
Done when: Confirmed closed roles exit active search yet remain viewable from user histories as Closed; temporary 503 does not retire valid roles.

### O-09 — Opportunity history and change summaries

Priority / status: P2 · NEW  
Why: Deadlines, compensation and requirements can change after users save a role.  
How: Retain field-level change history for material updates and show "deadline updated" with source timestamps; notify saved users according to preference and importance.  
Done when: Re-crawl with changed deadline creates one meaningful change event and no repeated alerts from text formatting changes.

### O-10 — Structured reporting and corrections

Priority / status: P0 · DOCUMENTED / IMPROVE  
Why: Aspirova already directs users to report wrong or closed listings; reports must feed operational action.  
How: Provide categories (closed, duplicate, bad location, misleading pay, scam, wrong source, inappropriate content), optional notes, rate limits and privacy-aware handling. Route to moderation queue and track resolution.  
Done when: Reports create actionable records and severe safety reports can trigger immediate review/quarantine.

## 4. Authentication, profile, settings and privacy controls

### A-01 — Robust sign-in, registration and account linking

Priority / status: P0 · VERIFY  
Why: Identity problems lose saved data and create subscription/support issues.  
How: Inventory current Google/email flows; handle OAuth state/nonce/PKCE as appropriate, duplicate identity collisions, invalid/expired sessions and callback failure. Offer safe account linking after identity proof rather than silently merging emails.  
Done when: Sign-in/out/re-auth and account-switch tests pass; same user cannot unintentionally create disconnected histories; CSRF/session tests pass.

### A-02 — Editable personal and education profile

Priority / status: P0 · VERIFY / IMPROVE  
Why: Matching needs durable, correct and user-controlled background data.  
How: Add or verify names, location, institution, degree, major, batch, graduation year, optional CGPA, academic status and current interests. Validate dates/lengths; allow a "prefer not to say" path for optional metrics.  
Done when: Changes persist across reload/devices; API enforces user ownership; partial updates do not wipe unrelated fields.

### A-03 — Skills, interests and career objectives

Priority / status: P1 · VERIFY / IMPROVE  
Why: Listing recommendations based only on broad categories quickly become noisy.  
How: Support normalized skills plus free text, preferred role families, industries, experience level, opportunity types and technologies. Map aliases and avoid duplicate labels.  
Done when: Editing a skill or preference updates future matching/alerts without requiring a fresh account.

### A-04 — Profile completeness with useful next actions

Priority / status: P1 · NEW / VERIFY  
Why: Users need guidance about which information genuinely improves recommendations.  
How: Assign weights to essential career preferences; show missing useful fields with inline edit links. Do not make previous job experience or a profile photo mandatory for student profiles.  
Done when: Completion is calculated server-side or from a single consistent source and remains stable after reload; no artificial 100% blockers.

### A-05 — Projects, work experience and certifications

Priority / status: P1 · NEW / VERIFY  
Why: Student capability is often better evidenced by projects than paid experience.  
How: Provide repeatable entries for title, dates, description, skills, links, outcomes and optional media. Validate and sanitize external URLs. Separate work, research, volunteering and academic projects.  
Done when: Entries can be added, reordered, edited and deleted without affecting others; private notes are not exposed publicly.

### A-06 — External links and portfolio connections

Priority / status: P1 · NEW / VERIFY  
Why: GitHub, LinkedIn, portfolios and design profiles help personalize role recommendations.  
How: Support validated platform URLs, link previews only with safe fetching, and per-link visibility controls. Do not request passwords or broad connected-account scopes merely to display links.  
Done when: Links are editable, sanitized and never become a script-injection vector.

### A-07 — Resume upload, replace, download and delete

Priority / status: P0 · VERIFY  
Why: Resume functionality handles sensitive personal documents.  
How: Use private object storage, short-lived signed retrieval, MIME/content validation, strict file-size limits, malware scanning where possible, retention policies, and explicit deletion of file plus derived text according to disclosed rules.  
Done when: User A cannot obtain User B's resume; replacement doesn't orphan public files; delete/retry/error behavior is tested.

### A-08 — Multiple resume versions and optional cover letters

Priority / status: P2 · NEW  
Why: Applicants target different roles using different CVs.  
How: Allow named resume versions, an optional default, version mapping to applications, and controlled retention. Later add cover-letter templates without inventing facts or requiring AI.  
Done when: A tracked application retains which version user selected even if the default resume changes.

### A-09 — Personalized defaults and preference sync

Priority / status: P0 · OBSERVED / VERIFY  
Why: Country, work mode, role interests and sort preferences should not reset unexpectedly.  
How: Make profile-backed preferences the default for members with URL overrides for a given search. Use a predictable precedence: explicit query > saved search > account preferences > safe system default.  
Done when: Preference changes survive session/device changes and do not silently overwrite an active filter selection.

### A-10 — Dedicated notification preferences and quiet hours

Priority / status: P0 · VERIFY / IMPROVE  
Why: High-volume alerts create unsubscribes and distrust.  
How: Separate opportunity, company, deadline, account and billing notifications; allow channels and cadence by category; support timezone-specific quiet hours and a global pause (except essential transactional/security notices).  
Done when: User controls are respected end-to-end by background workers and email providers.

### A-11 — Account security center

Priority / status: P0 · VERIFY  
Why: Users must protect profile, resumes and billing details.  
How: Display linked methods, recent activity where defensible, active sessions and sign-out-all; protect security changes with re-authentication. Set secure cookies, expiration/rotation and CSRF protection for state changes.  
Done when: Revoked sessions stop accessing private endpoints; privilege and account takeover tests pass.

### A-12 — Data export, deletion and consent controls

Priority / status: P0 · VERIFY  
Why: Students need transparent control over personal data and lawful handling.  
How: Add machine-readable export of profile, saves, alerts and application statuses; request account deletion with confirmation/re-auth; implement retention/deletion across DB, uploads and queues, subject to legal record obligations. Record separate marketing consent.  
Done when: Deletion removes personal records from active systems as promised and discloses exceptions; export cannot include another user's data.

### A-13 — Privacy-by-default visibility

Priority / status: P0 · NEW / VERIFY  
Why: Student profiles may include phone, academic metrics and resumes.  
How: Keep profiles private by default; only introduce public profiles with specific opt-in and per-field visibility. No employer access without a defined product contract and user consent.  
Done when: Public endpoints cannot expose emails, resumes, application notes or educational metrics by guessing IDs.

### A-14 — Account lifecycle and error recovery

Priority / status: P1 · VERIFY  
Why: Users can get stuck after expired sessions, failed OAuth callbacks or abandoned onboarding.  
How: Design friendly error pages, retry mechanisms, support links, session-expired banners, correct post-auth return destinations and robust sign-out. Preserve non-sensitive intent from the page visited before login.  
Done when: Every auth error has a recovery path and no redirect loop appears.

## 5. Saved items, user activity and application tracking

### T-01 — Reliable Save/Unsave and saved collections

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Saving is the lowest-friction way to organize opportunities.  
How: Use idempotent saves keyed by user and canonical opportunity, optimistic UI with rollback, a saved list with filters, and Undo. P1 enhancement: collections such as Dream Companies, Summer 2027, Research.  
Done when: Repeated click/retry doesn't duplicate saves and deletion never affects another user.

### T-02 — Audit and refine the existing application tracker

Priority / status: P0 · DOCUMENTED / VERIFY  
Why: Aspirova FAQ already states users can track applications; rebuilding it blindly risks breaking production.  
How: Find the actual tracker route/data model. Confirm states and allow a progression such as Saved, Planning, Applied, Assessment, Interview, Offer, Rejected, Withdrawn, plus Custom. Distinguish status changes from external Apply clicks.  
Done when: Full tracker flow is demonstrated with persistent history and no false auto-applied state.

### T-03 — Application details, notes and dates

Priority / status: P1 · IMPROVE / VERIFY  
Why: Users need context when several employers contact them.  
How: Store user-entered application date, role, source link, location, selected resume version, notes, follow-up date, interview schedule and outcome. Allow private attachments only with explicit scope and storage controls.  
Done when: Edits sync across devices and sensitive notes remain accessible only to the owner.

### T-04 — External application return-and-track flow

Priority / status: P0 · DOCUMENTED / IMPROVE  
Why: Aspirova can't know an employer-site submission succeeded.  
How: Record only "Apply link opened" event. After user returns, ask "Did you submit your application?" with Mark Applied / Not Yet / Don't Ask. Never infer completion from opening a tab.  
Done when: Click-only behavior leaves application status unchanged; manual confirmation creates an explicit user event.

### T-05 — Deadline calendar and reminders

Priority / status: P1 · NEW / VERIFY  
Why: Deadlines and interviews are time-sensitive.  
How: Build calendar view and ICS download; optionally connect calendar with user-granted scope in a later phase. Store timestamps in UTC plus source timezone and show local timezone clearly.  
Done when: Midnight/timezone edges and date-only deadlines display consistently; reminders don't double send.

### T-06 — Duplicate application and closed-role warnings

Priority / status: P1 · NEW  
Why: Users may apply twice or waste time on closed postings.  
How: On opening a role, check application tracker by canonical opportunity/ATS requisition; show existing status and closed source warning without blocking deliberate revisits.  
Done when: Duplicate across two data sources triggers a warning but distinct cohorts are not merged.

### T-07 — Bulk management and filtered worklists

Priority / status: P1 · NEW / VERIFY  
Why: Active users need to organize dozens of saves quickly.  
How: Add multi-select, bulk remove, bulk move to collection, filtered statuses, sort by deadline/date/company and undo. Run authorization checks on every batch item.  
Done when: Partial failures are clear and no hidden item is modified without the user's selection.

### T-08 — User-controlled activity timeline

Priority / status: P2 · NEW  
Why: A chronological record reduces confusion about application actions and role changes.  
How: Record saved, applied (manual), status changed, reminder scheduled and changed deadline events with provenance and timestamp. Provide data deletion/export consistent with account policy.  
Done when: Timeline distinguishes automated listing updates from actions performed by the user.

### T-09 — Export of personal search/workspace data

Priority / status: P1 · NEW / VERIFY  
Why: Users may organize applications in spreadsheets or other personal tools.  
How: Offer CSV export for saved searches/application tracker and ICS for deadlines; guard formulas against CSV injection and sanitize public/private field selection.  
Done when: Exports round-trip in common spreadsheet tools safely and never leak another account's data.

## 6. Alerts, digests, notifications and dream companies

### N-01 — Dream-company follow/unfollow and preference controls

Priority / status: P0 · DOCUMENTED / IMPROVE  
Why: FAQ states Pro offers more company tracking; the company-follow lifecycle must be reliable and understandable.  
How: Inspect current follows/limits; add Follow CTA to company pages/cards, list of followed companies, optional country/role constraints and subscription-limit messaging. Store canonical company ID rather than mutable company name.  
Done when: Follow/unfollow changes persist and produce only matching future notifications.

### N-02 — Saved-search notifications

Priority / status: P1 · NEW / VERIFY  
Why: Users should not repeat the same search every day.  
How: Match newly eligible opportunities against stored normalized filters; allow alert cadence, channel and per-search pause. Version matcher rules so users know when criteria change.  
Done when: A role passing filter conditions sends at most one new-alert per user/search/event, barring explicit reactivation logic.

### N-03 — Notification deduplication and idempotency

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Reprocessing a listing must not overwhelm users with redundant alerts.  
How: Generate canonical event IDs (user, opportunity, rule, event type, meaningful version) with DB uniqueness; use transactional outbox and worker retry with provider idempotency where available.  
Done when: Repeated ingestion, worker restart and delivery retry create one user-visible notification for one meaningful event.

### N-04 — Notification inbox: read, unread, bulk actions

Priority / status: P0 · OBSERVED / VERIFY  
Why: The examined logged-in homepage showed a high unread count; users need manageable inbox hygiene.  
How: Implement read/mark-unread, mark-all-read, delete/archive, categories, pagination and filter by unread. Use unread-count endpoint based on source of truth, with optimistic rollback.  
Done when: Header badge and inbox count agree after any action across tabs/devices.

### N-05 — Daily digest reliability and personalization

Priority / status: P0 · DOCUMENTED / IMPROVE  
Why: A free daily digest is an advertised baseline promise.  
How: Schedule according to user timezone; include only genuinely relevant and fresh opportunities, cap message size, link to preferences, suppress duplicates and honor unsubscribes. Add digest-preview and last-sent status.  
Done when: Delivery logs show one digest per opted-in period, no repeated unchanged listing spam and proper opt-out.

### N-06 — Pro instant alerts and premium entitlements

Priority / status: P0 · DOCUMENTED / VERIFY  
Why: Paid instant alerts must work as promised and differ transparently from free digests.  
How: Validate plan-gated alert cadence, quotas, billing transitions and backfilled alerts; provide bounded service-level targets without unsupported "real time" guarantees. Deny unauthorized plan access server-side, not solely in UI.  
Done when: Free/Pro cases match the pricing contract; upgrade/downgrade is atomic and tested.

### N-07 — Deadline and saved-role change alerts

Priority / status: P1 · NEW / VERIFY  
Why: A saved role's deadline or open status can change unexpectedly.  
How: Send configurable due-in-7/3/1-day reminders for source-backed deadlines; detect material deadline/status changes and deduplicate. Respect quiet hours except consciously designed urgent notices.  
Done when: UTC and timezone-based tests pass; no reminders send for confirmed closed opportunities.

### N-08 — Per-channel subscriptions and unsubscribe compliance

Priority / status: P0 · VERIFY  
Why: Users need control over email/browser/optional messaging notifications.  
How: Build a channel-by-topic preference matrix; separate security/payment transactional notices; use email unsubscribe mechanism and suppression lists. Obtain explicit consent before web push or WhatsApp.  
Done when: Unsubscribe changes both database and provider behavior; suppressed accounts receive no marketing emails.

### N-09 — Explain "Why did I receive this?"

Priority / status: P1 · NEW  
Why: Relevance and trust improve when users can see alert match reasons.  
How: Attach alert rule name, matched company/role/location criteria and exact new or changed fields; let user adjust preferences from notification. Avoid exposing sensitive data in push previews.  
Done when: Every opportunity alert has a comprehensible and reproducible trigger reason.

### N-10 — Notification delivery observability

Priority / status: P0 · NEW / VERIFY  
Why: Missing alerts and duplicate alerts are difficult to diagnose without traceable events.  
How: Track queued/sent/provider-accepted/delivered/bounced/failed where signals exist, per template and channel. Add retry with exponential backoff and dead-letter handling, dashboards and rate limiting.  
Done when: Support can investigate a user alert via event ID without needing to read private resume content.

### N-11 — Weekly report usefulness and accountability

Priority / status: P1 · DOCUMENTED / IMPROVE  
Why: A Pro weekly report should save actual decision time rather than repackage generic search results.  
How: Include new matching opportunities, deadlines, followed-company activity, application progress and missed opportunities with accurate attribution. Make weekly report opt-out/configurable and explain any unavailable data.  
Done when: Reports are deterministic for a given snapshot, don't claim unverified applications, and differ meaningfully from daily digest.

## 7. Resume analysis, role matching and explainability

### R-01 — Robust resume parser and user review step

Priority / status: P0 · OBSERVED / VERIFY  
Why: Faulty extraction undermines every downstream recommendation.  
How: Parse PDF/text with fallbacks; store normalized skills, projects, education and experience separately from raw text; show confidence and allow users to edit incorrectly extracted information before using it in matching. Don't fabricate fields from sparse resumes.  
Done when: Two-column, scanned (where supported), text-heavy and malformed file fixtures degrade gracefully and never silently invent qualifications.

### R-02 — Transparent match signals rather than opaque probabilities

Priority / status: P1 · OBSERVED / IMPROVE  
Why: A match score can falsely imply eligibility or hiring likelihood.  
How: Separate hard requirements from soft relevance. Display matched skills, missing evidence, explicit blockers and Unknowns. If using a score, label it "profile relevance" and document its source and limitations.  
Done when: A user can understand a rating; no score is described as the chance of receiving an interview or offer.

### R-03 — Source-backed skill and requirement extraction

Priority / status: P1 · NEW / VERIFY  
Why: Generative summaries can confuse "required" with "preferred" skills.  
How: Store requirement spans and original source offsets where feasible; classify must-have/nice-to-have with confidence; allow Unknown and manual correction. Prefer rules/extraction models with benchmarks over unrestricted generative inference.  
Done when: QA samples show traceable source snippets for important requirements and controlled false positives.

### R-04 — Resume-to-role actionable suggestions

Priority / status: P2 · NEW  
Why: Users want to know how to improve a resume, not just receive a numerical score.  
How: Suggest explicitly evidenced skills/projects to emphasize, missing proof, formatting/clarity changes and optional keywords; block fabricated experience or achievements. Require user review before copying changes.  
Done when: Suggestions cite user-provided content and do not add unverified credentials or promises of ATS success.

### R-05 — Skills outside the resume

Priority / status: P1 · NEW  
Why: Students may know a tool or have a project that is omitted from a one-page CV.  
How: Let users edit a private skills profile and mark evidence sources (coursework, project, experience, self-reported). Do not treat self-report as independently certified.  
Done when: Profile and resume signals can differ, users can control each, and explanations identify which source contributed.

### R-06 — Cold-start recommendations

Priority / status: P1 · NEW / VERIFY  
Why: New users without resumes still need useful search results.  
How: Rank by selected interests, location, opportunity category and freshman/graduate profile with a generic fallback. Provide explicit controls to change preference assumptions.  
Done when: A user with zero resume data gets relevant non-empty results where matching opportunities exist.

### R-07 — Feedback loop and measurable ranking improvements

Priority / status: P1 · IMPROVE  
Why: Recommendation quality improves only when users can disagree with results.  
How: Collect Not relevant / Interested / Already applied / Hide, with per-user preference impact. Keep aggregate evaluation privacy-preserving and avoid discriminatory use of sensitive attributes.  
Done when: Feedback updates later rankings and can be reversed or reset by users.

### R-08 — Optional role comparison and resume versions

Priority / status: P2 · NEW  
Why: Choosing between multiple roles involves tradeoffs not captured by one score.  
How: Compare up to a small set by location, pay, eligibility, deadline and skills; show Missing as Unknown instead of blank/zero; optionally recommend a user's resume version without submitting it.  
Done when: Side-by-side values retain original source semantics and no applications are submitted automatically.

## 8. Ingestion pipeline, listing quality, provenance and safety

### Q-01 — Canonical source IDs and provenance model

Priority / status: P0 · IMPROVE / VERIFY  
Why: Opportunities arrive from different sources with inconsistent IDs and titles.  
How: Keep raw source record, source domain, original URL, external requisition ID, fetch timestamp, parser version, source content hash and normalized record. Deduplicate via a canonical opportunity entity linked to many provenance records.  
Done when: Every public listing can be traced to a source; normalized changes do not erase raw evidence needed for correction.

### Q-02 — Distinct event timestamps and freshness vocabulary

Priority / status: P0 · IMPROVE  
Why: Crawl frequency must never be presented as posting age.  
How: Introduce separate source_posted_at, first_seen_at, last_seen_at, last_checked_at, last_confirmed_open_at, deadline_at, closed_at, each nullable as appropriate. Migrate existing fields with unknown provenance to Unknown rather than assigning false dates.  
Done when: One old role re-crawled daily stays old in Latest sort; timestamp QA fixtures pass.

### Q-03 — Employer, location and region canonicalization

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Malformed locations and duplicate employer names cause bad search results and alerts.  
How: Normalize country ISO, region, city and remote-mode fields separately, preserve original text, and maintain a manual override queue. Treat ambiguous place names cautiously; never geocode to a random city on name collision.  
Done when: Location display and filters agree; sampled ambiguous locations are queued for review instead of misclassified.

### Q-04 — Remote, hybrid and local-work restrictions

Priority / status: P0 · IMPROVE  
Why: Remote within one country is materially different from worldwide.  
How: Model work_mode, work_countries, preferred_office_locations, relocation, visa_required and source confidence distinctly. Use Unknown where unproven.  
Done when: Country filters can distinguish "remote from India" from "remote in United States only".

### Q-05 — Stipend/salary normalization and disclaimer

Priority / status: P0 · IMPROVE  
Why: Search sorting and card trust depend on accurate units.  
How: Parse currency, period, min/max, base/variable and unpaid explicitly; store raw string; do not automatically convert annual to monthly if ambiguity exists. Use rate snapshot if cross-currency conversion is provided.  
Done when: Currency and unit fixture suite passes; unspecified pay never becomes zero or unpaid.

### Q-06 — Category and seniority classification

Priority / status: P0 · IMPROVE  
Why: Mixed jobs, internships, apprenticeships and events degrade category accuracy.  
How: Apply a hierarchical taxonomy with source-backed classification and confidence. Separate role category, employment type and experience level; log low-confidence results for review.  
Done when: Benchmarked examples including graduate roles, PhD internships, apprenticeships and senior jobs are categorized appropriately.

### Q-07 — Duplicate clustering without false merges

Priority / status: P0 · IMPROVE  
Why: The same role may be syndicated, but similar titles across locations/cohorts may be distinct positions.  
How: Combine exact ATS requisition IDs, canonical URLs and conservative fuzzy matching; preserve source alternatives and region/cohort differences. Maintain merge/split audit trail.  
Done when: Known cross-source duplicates group, while two different requisitions remain separate.

### Q-08 — Open/closed state detection with retries

Priority / status: P0 · IMPROVE  
Why: Source sites change and intermittently fail.  
How: Treat confirmed status, explicit past deadline, redirects, 404/410, temporary 403/429/5xx and browser-rendered state differently. Revalidate with backoff and per-source rules. Avoid harvesting or bypassing blocked sites contrary to source terms.  
Done when: Source outages do not mass-close roles; true closed positions retire within a stated operational window.

### Q-09 — Company authenticity and scam reporting

Priority / status: P0 · IMPROVE  
Why: Aggregated postings may include misleading or malicious intermediaries.  
How: Score source trust by official domain/ATS verification, identity/domain association and moderation signals; label claims precisely. Add red flags for application fees, identity-document demands and suspicious redirect chains; maintain review and appeal process.  
Done when: Serious scam reports reach a review queue with source snapshot; false "verified employer" badges are prohibited.

### Q-10 — Data extraction QA and regression dataset

Priority / status: P0 · NEW / VERIFY  
Why: Parser changes can corrupt thousands of listings silently.  
How: Build golden fixtures per source/provider with expected title, company, location, compensation, type, deadline and URL. Run parser regression tests before crawler deployments; sample live output daily.  
Done when: A parser release is blocked if critical fields regress beyond agreed thresholds.

### Q-11 — Per-source health and freshness dashboards

Priority / status: P0 · NEW / VERIFY  
Why: An aggregate "updated daily" claim conceals source outages.  
How: Instrument last success/failure, ingestion count, parse success, stale rate, duplicates, open-link error rate, latency and quota/rate-limit status per source. Alert on anomalies with source ownership.  
Done when: Operators can identify which source is stale, and public freshness messages don't exaggerate coverage.

### Q-12 — Safe crawling, robots/terms and rate limits

Priority / status: P0 · VERIFY  
Why: Source ingestion must be ethical, maintainable and resilient.  
How: Prefer official APIs/feeds and permitted pages; honor source terms and crawl policies; rate-limit, backoff and cache; never bypass access controls, CAPTCHAs or authentication. Keep a per-source collection policy.  
Done when: Source connectors have documented allowed access method, limits, retries and owner.

### Q-13 — Deletion, correction and appeal workflows

Priority / status: P1 · NEW / VERIFY  
Why: Source providers/employers may request correction or removal, and users report errors.  
How: Build correction requests, moderation status, immutable audit trail, source-specific override TTL and resolution messages where appropriate. Do not silently override authoritative new source data forever.  
Done when: Each actionable request has a decision, owner and traceable resolution.

### Q-14 — Public trust and source explanation

Priority / status: P1 · DOCUMENTED / IMPROVE  
Why: Aspirova's source-first promise is a central differentiator.  
How: Show a short source-methodology page and on-page last-check context; clarify that open status and eligibility can change, and original listing prevails. Don't present an unsupported verification guarantee.  
Done when: Users understand where the role came from and how to report a discrepancy.

## 9. Companies, sectors and dream-company collections

### C-01 — Complete company detail pages

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Company pages are useful entry points for users with preferred employers.  
How: Provide canonical company name, official careers link, sector/tags, current open opportunities by type/location, recent verified postings and follow CTA; distinguish sourced facts from editorial description.  
Done when: Company totals reconcile with active canonical listings and dead company links show graceful fallback.

### C-02 — Canonical company identities and aliases

Priority / status: P0 · IMPROVE  
Why: Multiple source spellings lead to duplicate pages and fragmented alerts.  
How: Establish stable company IDs with aliases, official domains and parent/subsidiary distinctions where meaningful; maintain merge/split history.  
Done when: A company follow remains functional after an alias or slug changes.

### C-03 — Followed companies feed and change log

Priority / status: P1 · NEW / VERIFY  
Why: Users should quickly see what changed at their target employers.  
How: Build a Following tab with newly opened roles, exact deadline changes and location filters; show already seen roles separately.  
Done when: Followed-company feed contains only canonical matches and doesn't list repeatedly re-crawled roles as newly opened.

### C-04 — Dream-company lists and preference bundles

Priority / status: P1 · NEW / VERIFY  
Why: Students typically track a set of target employers, not isolated names.  
How: Support user-defined collections and default role/location alert filters per collection. Respect current Pro capacity limits and avoid silent data loss on downgrade.  
Done when: Users can follow/unfollow and manage list-level alerts with clear entitlement limits.

### C-05 — Companies by field/industry and early-career footprint

Priority / status: P2 · NEW  
Why: Students discover companies beyond familiar large brands.  
How: Build taxonomy-based browsing for AI, fintech, consulting, product, research, design and other verticals, with counts of actual current student/graduate roles rather than total corporate vacancies.  
Done when: Category counts are explainable, filterable and not inflated by senior roles.

## 10. Competitions, research, scholarships, fellowships and programmes

### K-01 — Category-specific schemas and filter UX

Priority / status: P0 · OBSERVED / IMPROVE  
Why: Events, grants and research opportunities have different fields from jobs.  
How: Use a shared Opportunity base plus typed fields per category; avoid forcing job salary/experience fields onto hackathons. Adapt search facets and card content to each category.  
Done when: Each category shows the fields users need, with appropriate Unknown handling.

### K-02 — Hackathon and competition discovery

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Team size, stages and prizes drive participation decisions.  
How: Index registration deadline, event date, organizer, theme, prize, team rules, online/offline, venue and official source. Separate registration from submission deadlines.  
Done when: A competition's two deadlines cannot be confused and source-derived eligibility is visible.

### K-03 — Research roles and academic fit

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Research roles often require particular degree level, supervisor and domain.  
How: Include host lab, supervisor (when public), focus area, degree/CGPA requirements, funding, application documents and faculty/institution link. Support Undergraduate / Master's / PhD filters.  
Done when: PhD-only research internships do not display as confirmed eligible for undergraduates.

### K-04 — Scholarship eligibility and required documents

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Scholarship decisions hinge on hard conditions and document burden.  
How: Model citizenship/residency, level of study, financial/academic eligibility, scholarship value, renewal conditions, required documentation and deadlines. Sensitive personal financial attributes should not be inferred or collected unless required and justified.  
Done when: Unknown criteria remain visible as unknown and no scholarship is falsely marked "eligible".

### K-05 — Programme and fellowship chronology

Priority / status: P1 · OBSERVED / IMPROVE  
Why: Programmes may have cohort windows, fees and multi-stage applications.  
How: Support cohorts/start date, program duration, cost/funding, age/education criteria, organizer, stages and selection result dates.  
Done when: Programme cards show critical fee/deadline info and apply links go to the organizer.

### K-06 — Common personal calendar across categories

Priority / status: P1 · NEW  
Why: Users need a single view of deadlines for jobs, scholarships and competitions.  
How: Normalize date-only and timestamp deadlines into calendar events with type, source, timezone and confidence; allow filtering and ICS export.  
Done when: All categories appear in a single calendar without inventing missing timestamps.

### K-07 — Optional team discovery for competitions

Priority / status: P3 · NEW  
Why: Finding teammates is a genuine obstacle but introduces moderation and privacy costs.  
How: Only after consent, moderation and anti-harassment mechanisms exist, allow opt-in profiles and team requests, rate limits, blocking/reporting, and safe contact controls.  
Done when: Users can opt out, report abuse and control who sees their contact information; no public exposure by default.

## 11. Pricing, premium value, payments and billing

### B-01 — Transparent plan comparison and pricing explanation

Priority / status: P0 · DOCUMENTED / VERIFY  
Why: Users must know what Free and Pro provide before payment.  
How: Display current plan limits: daily digest versus instant alerts, weekly report and company-follow capacity. Clearly show billing period, currency, taxes, renewals, cancellation rules, refunds and any trial conditions. Derive entitlements from one server-side source of truth.  
Done when: Pricing copy, checkout and actual entitlements match exactly across devices.

### B-02 — Keep core access free and source links unblocked

Priority / status: P0 · DOCUMENTED / PROTECT  
Why: A source-first platform's credibility depends on unimpeded public opportunity access.  
How: Do not put basic browsing, core search, job safety information, reporting or original-source applications behind payment. Make paid benefits speed/capacity/convenience, not access to employer applications.  
Done when: A free user can view eligible public listing details and follow the original application route without purchase.

### B-03 — Payment flow correctness and failure recovery

Priority / status: P0 · VERIFY  
Why: Payment inconsistencies damage trust and may cause financial loss.  
How: Use provider-hosted or supported checkout, signed webhooks, idempotency keys, state machine (created/pending/paid/failed/refunded), retries and reconciliation. Never grant entitlements based only on a client success redirect.  
Done when: Duplicate callback, interrupted browser, failed card and late webhook tests preserve a single correct charge/plan state.

### B-04 — Subscription or time-limited plan lifecycle

Priority / status: P0 · VERIFY  
Why: Renewal and cancellation semantics must match how the current product actually sells Pro.  
How: Determine whether plans are recurring or one-time before implementing. For recurring plans, offer cancel-at-period-end, renewal notice and grace/failure states. For fixed-duration passes, show exact expiry and no auto-renew by default.  
Done when: Every plan type has correct effective, expiry and cancellation timestamps without ambiguous auto-renew claims.

### B-05 — Billing history, receipts, invoice and taxes

Priority / status: P0 · VERIFY / IMPROVE  
Why: Paying students expect a credible transaction record and support path.  
How: Show transaction ID, date, plan, paid amount, taxes, status, downloadable receipt/invoice as appropriate and payment-support contact. Protect sensitive payment tokens; don't store card data outside provider.  
Done when: Billing history reconciles with provider and only the account owner can access documents.

### B-06 — Upgrade/downgrade without losing user data

Priority / status: P0 · VERIFY  
Why: Users may track more companies than a downgraded plan permits.  
How: Define deterministic entitlement transitions: preserve extra follows but pause excess premium alert rules with clear selection, or provide user-managed prioritization. Never silently delete follows, resumes or application notes.  
Done when: Plan transition tests cover boundary quotas, refunds and expired access with understandable UI.

### B-07 — Premium value preview and conversion UX

Priority / status: P1 · IMPROVE  
Why: Students subscribe when benefits are tangible and accurately described.  
How: Show examples of instant company alerts and weekly report previews with clear sample labels. Place upgrade prompts at relevant limits rather than repetitive interruptions. Do not claim a job-placement advantage.  
Done when: Feature gates communicate what happens on upgrade and never block a free feature by error.

### B-08 — Referral programme integrity

Priority / status: P1 · OBSERVED / VERIFY  
Why: Aspirova links to Invite/Referral; abuse can distort acquisition economics.  
How: Audit referral rules; track eligible conversion events server-side, prevent self-referrals, device farms and duplicate rewards, and disclose rewards/expiry. Respect marketing consent and referral data privacy.  
Done when: One qualified conversion creates no more than the permitted benefit, with reversible fraud review.

### B-09 — Help center, refund and billing support

Priority / status: P0 · DOCUMENTED / IMPROVE  
Why: Users require quick resolution when payment or entitlement differs from what was promised.  
How: Connect FAQ, refund policy, receipts and ticket forms; include payment-reference field rather than asking for sensitive card details. Define response categories and support SLAs internally.  
Done when: A user can file and track a billing issue without sharing full card/account secrets.

## 12. Mobile experience, accessibility, localization and SEO

### U-01 — Mobile-first cards, search and filter drawer

Priority / status: P0 · OBSERVED / VERIFY  
Why: Students frequently browse links on small screens.  
How: Audit breakpoints, sticky search/filter affordance, filter drawer Apply/Reset, one-hand Save/Apply controls and card density. Respect safe-area insets and software keyboard height.  
Done when: Popular 320–430px layouts work without sideways scrolling, clipped controls or touch-target conflicts.

### U-02 — Accessible navigation and semantic structure

Priority / status: P0 · OBSERVED / VERIFY  
Why: Buttons, menus and drawers must be operable without a mouse.  
How: Use semantic headings, landmarks, accessible names, focus traps for modal dialogs, logical tab order, skip link and visible focus. Honor reduced motion.  
Done when: Automated a11y scans pass plus manual keyboard and screen-reader flows for Search → Detail → Save → Account.

### U-03 — WCAG-aligned color contrast and state semantics

Priority / status: P0 · VERIFY  
Why: Tiny metadata and low-contrast badges are common issues in card-heavy products.  
How: Audit contrast in both themes, error/disabled/focus states and color-only labels. Ensure Save, Closed, Eligible and Deadline states have text/icons as well as color.  
Done when: Critical text/control contrast meets adopted WCAG target (recommend 2.2 AA) and state is understandable in grayscale.

### U-04 — Loading, offline, retry and empty experiences

Priority / status: P0 · VERIFY  
Why: Slow networks and rate limits can make site appear broken.  
How: Design skeletons, clear empty results, retry with backoff, preserved form state and informative maintenance messages. Avoid infinite spinners or silent failures.  
Done when: Offline, throttled, 404 and 500 cases are navigable and never erase user's draft or preferences.

### U-05 — Browser navigation and scroll restoration

Priority / status: P1 · VERIFY  
Why: Users repeatedly return to the previous search after checking details.  
How: Persist query params and selected tab; use router scroll restoration or custom state with stable identifiers. Handle pagination and browser Back/Forward cleanly.  
Done when: Returning from role detail restores list position/filter without stale content mismatches.

### U-06 — Performance and Core Web Vitals

Priority / status: P0 · VERIFY  
Why: Heavy result grids can harm usability and organic discovery.  
How: Instrument real-user LCP/INP/CLS; aim for good thresholds (LCP ≤2.5s, INP ≤200ms, CLS ≤0.1 at 75th percentile), optimize fonts, logos, server queries and image dimensions. Cache list queries cautiously; isolate personalized data.  
Done when: Real-user vitals move to good range for target segments without personalized cache leaks.

### U-07 — Accessibility of notifications, dates and status changes

Priority / status: P1 · VERIFY  
Why: Dynamic counts and filter updates need understandable announcements.  
How: Use accessible status messages for search results and save success; use human-readable date labels with machine datetime; limit noisy live regions.  
Done when: Assistive-tech users can identify current result count, selected filters and latest action outcomes.

### U-08 — Search engine discoverability and structured data

Priority / status: P1 · VERIFY  
Why: Public opportunity pages can be discovered through search engines, but inaccurate structured data is risky.  
How: Add canonical URLs, sitemap and robots strategy, meaningful title/meta, clean pagination, and schema.org JobPosting only for appropriate active jobs with genuinely sourced fields. Remove expired jobs from eligible job structured data. Do not markup competitions as jobs.  
Done when: Canonical/indexation tests pass; no false salary, hiring organization or expired-state fields are emitted.

### U-09 — Localization and currency/location presentation

Priority / status: P2 · NEW / VERIFY  
Why: International listings require clarity over formats, not necessarily full translation at first.  
How: Localize date/time formats and currency symbols with original currency retained; display country and timezone; consider language translation only after source-text rights and QA are established.  
Done when: An Indian user viewing an overseas role sees unambiguous location, currency and deadlines.

### U-10 — Optional installable PWA

Priority / status: P2 · NEW  
Why: Regular users may want faster access without a native mobile app.  
How: Add manifest, icons and limited offline shell. Never cache private resumes, sensitive account responses or stale opportunity data indiscriminately. Consider push only with explicit opt-in.  
Done when: Installation works and cache partitioning passes multi-account/privacy checks.

## 13. Security, privacy, compliance and abuse prevention

### SEC-01 — Authorization audit across private resources

Priority / status: P0 · VERIFY  
Why: Saved roles, resumes, application notes and billing must never leak between users.  
How: Enforce server-side ownership/RBAC on all read/write endpoints, test direct object references, enumerate tenant/user ID guesses and restrict admin access. Don't rely on client-side filtering.  
Done when: Cross-user negative test suite returns forbidden/not found appropriately for every private resource.

### SEC-02 — Secure file handling and sensitive-data minimization

Priority / status: P0 · VERIFY  
Why: Resumes contain personal contact and educational details.  
How: Restrict MIME/types/sizes, scan uploads where feasible, encrypt at rest/transit, use signed URLs, limit log content and redact exception traces. Retain minimum fields needed for product value.  
Done when: Files are private and deletion/retention jobs are provably effective within declared policy.

### SEC-03 — Security headers, XSS/CSRF and safe redirects

Priority / status: P0 · VERIFY  
Why: External links and user content expand attack surface.  
How: Validate URL protocols, encode user-generated fields, prevent script injection, enforce CSRF protection and secure session cookies, set practical CSP/HSTS/security headers, sanitize HTML from crawled descriptions.  
Done when: Security regression suite covers unsafe URL schemes, script payloads and unauthorized state-changing requests.

### SEC-04 — Abuse, scraping and rate-limit controls

Priority / status: P0 · VERIFY  
Why: Search endpoints, report forms, signup and referrals can be abused.  
How: Use bounded per-identity/IP endpoint limits, abuse scoring, CSRF/captcha only where justified, data exposure limits and cost controls on expensive matching queries.  
Done when: Load/security tests prevent denial-of-wallet while preserving reasonable human browsing.

### SEC-05 — Marketing consent and notification compliance

Priority / status: P0 · VERIFY  
Why: Email/WhatsApp/push may require separate opt-in and visible opt-out.  
How: Maintain timestamped purpose/channel consent, unsubscribe evidence, suppression handling, change logs and data processing documentation. Seek jurisdiction-specific legal review for launches.  
Done when: Consent can be audited and opt-outs stop non-essential messaging without blocking security notices.

### SEC-06 — Admin roles, moderation audit and secret management

Priority / status: P0 · VERIFY  
Why: Operators need moderation access, but should not gain unrestricted access to student data.  
How: Separate admin roles for source QA, content moderation, billing support and security; log privileged actions; rotate provider secrets and restrict production credentials.  
Done when: Least-privilege tests pass; sensitive admin actions are traceable.

### SEC-07 — Backups, disaster recovery and data deletion jobs

Priority / status: P0 · VERIFY  
Why: Data loss can erase months of user application history.  
How: Verify automated backups, recovery point/time objectives, restore drills, object storage retention and retention-aware deletion workflows. Reconcile backup retention with privacy promises.  
Done when: Restore drill succeeds and deleted user data is not accidentally resurrected into active accounts without safeguards.

## 14. Internal admin, product analytics, operations and quality assurance

### OPS-01 — Source monitor and ingestion quality dashboard

Priority / status: P0 · NEW / VERIFY  
Why: Broken crawlers and parser drift need fast diagnosis.  
How: Summarize source jobs, last success, parse failures, duplicate rates, active listing deltas, unexpected zeros and link availability. Flag anomalies by source and provide safe reruns.  
Done when: A mock connector outage triggers alert and dashboard cause analysis.

### OPS-02 — Content review and correction queue

Priority / status: P0 · NEW / VERIFY  
Why: Scam and inaccurate-data reports require a reliable human workflow.  
How: Queue reports with evidence, severity, source, decision, reviewer, reason and SLA. Allow quarantine, override with expiry and restoration.  
Done when: High-severity reports don't get lost and published changes have audit trail.

### OPS-03 — User-centric funnel analytics

Priority / status: P1 · NEW / VERIFY  
Why: Pageviews alone do not establish whether users find useful opportunities.  
How: Instrument search → detail → save → external Apply click → self-reported applied with consent/privacy protections. Avoid treating an Apply click as a completed submission.  
Done when: Dashboard distinguishes discovery, intent and confirmed-by-user application events.

### OPS-04 — Search and recommendation quality scorecard

Priority / status: P1 · NEW  
Why: More listings do not necessarily increase user value.  
How: Monitor zero-result rate, search-to-detail CTR, not-interested rate, saved-to-click rate, ineligible result rate and relevance benchmarks by role/country.  
Done when: Ranking releases include quality metrics and an explicit rollback threshold.

### OPS-05 — Alert quality and delivery scorecard

Priority / status: P0 · NEW / VERIFY  
Why: Alerts are a key premium promise and operational risk.  
How: Track eligible events, queued, provider accepted, delivered (if available), opened, clicked, duplicate suppression, unsubscribes and complaints. Monitor per-user volume distribution.  
Done when: On-call/support can distinguish no matching opportunity from delivery failure.

### OPS-06 — Error tracking and observability

Priority / status: P0 · VERIFY  
Why: Client-side errors, slow API calls and queue backlog can be silent.  
How: Add structured logs, trace IDs, exception monitoring, P95/P99 latencies, database pool health, queue depths and privacy-safe redaction. Set alerts for sustained failures rather than one-off noise.  
Done when: A synthetic failure points to the failing request/worker within minutes using trace correlation.

### OPS-07 — Feature flags, progressive rollout and rollback

Priority / status: P0 · NEW / VERIFY  
Why: Changes to filters, billing and alerts can disrupt existing users.  
How: Implement server-evaluated flags, staged cohorts, separate migration activation, kill switches and backward-compatible schemas; document rollback path before deploy.  
Done when: A new feature can be disabled without deleting user data or rolling back unrelated fixes.

### OPS-08 — Automated regression suite

Priority / status: P0 · VERIFY  
Why: Every release should preserve search, auth, saved, alerts, pricing and original links.  
How: Combine unit tests, integration tests against test DB, API contract tests and browser E2E journeys. Add golden ingestion fixtures; test permissions, race conditions and timezone boundaries.  
Done when: A release pipeline fails on major regressions and keeps reproducible failure artifacts.

### OPS-09 — Product feedback and public changelog

Priority / status: P1 · NEW / VERIFY  
Why: User feedback helps prioritize problems and demonstrates ongoing reliability.  
How: Provide simple feedback from relevant screens, categorize request/bug/scam separately, avoid duplicate feedback and publish concise release notes without exposing private tickets.  
Done when: Users can submit feedback and support can triage it by feature and severity.

### OPS-10 — Operational cost and margin safeguards

Priority / status: P0 · NEW / VERIFY  
Why: Low-cost student subscriptions can be overwhelmed by email, LLM, database and crawl costs.  
How: Track cost per active user, per alert, per weekly report and per source. Cache idempotently, cap LLM usage, batch digest work and send only valuable changes; set budgets and graceful fallback paths.  
Done when: Cost monitoring detects atypical per-user usage and premium delivery remains sustainable.

## 15. Optional future capabilities — do not build ahead of core quality

### FUT-01 — AI resume editor and cover-letter assistant

Priority / status: P2 · NEW  
Why: Some users want application preparation in one workspace.  
How: Offer an explicit optional draft assistant constrained to truthful user evidence, separate from matching, with clear AI disclosure, cost limits and export.  
Done when: It doesn't invent qualifications, apply for users or silently edit resumes.

### FUT-02 — User-facing career progress analytics

Priority / status: P2 · NEW  
Why: Users can benefit from seeing consistent search behavior and upcoming commitments.  
How: Show weekly saved/applied totals and upcoming deadlines with caveat that status is self-reported, plus personalized next steps. Avoid competitive or guilt-inducing streaks.  
Done when: Dashboard figures reconcile with the user's tracker history.

### FUT-03 — Preparation resources for opportunities

Priority / status: P2 · NEW  
Why: Candidates often need a quick guide to assessments and documents.  
How: Create curated, source-backed preparation checklists by role/competition rather than claiming interview-specific questions known only to employers.  
Done when: Content is accurate, versioned and clearly separated from original employer information.

### FUT-04 — College or graduating-batch experiences

Priority / status: P3 · NEW  
Why: Students may seek institution-specific and batch-specific opportunities.  
How: Offer opt-in filtered feeds and campus collections before attempting social networking; use verified institution membership only if necessary and privacy-preserving.  
Done when: College labels cannot be used to reveal a user's private identity or application activity.

### FUT-05 — Opt-in competition team matching

Priority / status: P3 · NEW  
Why: Competition participation sometimes depends on teaming up.  
How: Require moderation, block/report, scoped invitations and minimal publicly visible data before launching messaging.  
Done when: Users can fully control discoverability and escape abusive interactions.

### FUT-06 — Employer/ATS partnerships, not speculative direct applications

Priority / status: P3 · CONDITIONAL  
Why: Authorized integrations might improve status accuracy but change Aspirova's aggregator positioning.  
How: Only use formal, consent-based integrations with explicit API authorization and contractual scope. Keep third-party status separate from user-entered status.  
Done when: Each integration has permission, privacy, error and revocation documentation; no unsupported scraping of private application portals.

### FUT-07 — Native mobile app after PWA/retention validation

Priority / status: P3 · NEW  
Why: Native development is costly and not necessary to prove demand.  
How: First measure repeat mobile engagement and PWA limitations; build native only if push reliability, OS capabilities or retention clearly justify it.  
Done when: Business case includes acquisition, retention, support and app-store compliance implications.

# APPENDICES — IMPLEMENTATION HANDOFF

## Appendix A. Suggested technical models and contracts (adapt to existing schema)

Important: These are conceptual contracts, not a claim about Aspirova's current database structure or framework. Audit existing tables/columns first, re-use established entities, and avoid duplicate state stores. Schema extensions should be migration-based and additive whenever possible.

### A1. Canonical opportunity

```
Opportunity {
  id: stable internal ID
  category: internship | job | competition | scholarship | research | programme | fellowship | other
  title, company_id?, canonical_source_id, canonical_apply_url
  lifecycle_status: open | closed | uncertain | under_review
  seniority?: student | graduate | entry | mid | senior | unknown
  work_mode?: remote | hybrid | onsite | unknown
  countries_allowed[]?, office_locations[]?, work_authorization?: structured requirements
  source_posted_at?, first_seen_at, last_seen_at, last_checked_at?, last_confirmed_open_at?
  deadline_at?, deadline_timezone?, closed_at?
  compensation?: { min?, max?, currency?, period?, is_paid?, is_unpaid?, original_text? }
  duration?, eligibility?: requirements-with-source-evidence
  public_description?, normalized_skills[], source_content_version
  created_at, updated_at
}

OpportunitySource {
  id, opportunity_id, provider, source_url, employer_career_url?, external_requisition_id?
  source_record_hash, raw_payload_ref, fetched_at, parser_version, verification_result
  original_source_date?, confidence, last_error?
}
```

Implementation notes: Keep Unknown/null for unverified fields, source-specific payloads separate, employer IDs stable and index/filter fields explicit. Never store extracted text from third-party sites as if it were the authenticated user's content.

### A2. Private user data

```
UserPreferences { user_id, interests[], categories[], countries[], preferred_work_modes[],
                  salary_pref?, graduation_year?, degree?, timezone, modified_at }
SavedOpportunity { user_id, opportunity_id, collection_id?, saved_at, UNIQUE(user_id, opportunity_id) }
Application { id, user_id, opportunity_id, status, applied_at?, resume_version_id?, notes?,
              external_application_url?, created_at, updated_at }
ApplicationEvent { id, application_id, actor: user|system|integration, event_type,
                   previous_state?, next_state?, at, metadata }
CompanyFollow { user_id, company_id, collection_id?, notification_rule_id?, UNIQUE(user_id, company_id) }
SavedSearch { id, user_id, name, filter_json, sort, alert_enabled, cadence, last_evaluated_at? }
NotificationRule { id, user_id, subject_type, criteria_json, channel, cadence, timezone, paused }
NotificationEvent { id, user_id, rule_id?, opportunity_id?, event_kind, event_version,
                    dedup_key UNIQUE, created_at, read_at?, delivery_state }
ResumeVersion { id, user_id, display_name, private_object_key, parse_state, created_at, deleted_at? }
Entitlement { user_id, plan_code, started_at, expires_at?, status, limit_snapshot }
```

Privacy considerations: Implement row-level/endpoint ownership checks, separate payment-provider IDs from public response models, restrict file URLs to short-lived access, and avoid logging unredacted resumes, personal notes or payment secrets. The UNIQUE examples are illustrative; use actual DB conventions and account merge rules.

### A3. Suggested APIs/events (naming illustrative)

- GET /opportunities?category=&q=&country=&work_mode=&deadline_before=&cursor= — public, bounded, cache-safe search.
- GET /opportunities/:id — public normalized detail with original-source metadata; status must not be fabricated.
- POST /me/saved, DELETE /me/saved/:id — idempotent authenticated save.
- GET/PATCH /me/profile, GET/PATCH /me/preferences — validated, ownership-protected changes.
- GET/POST/PATCH /me/applications — manual application status and timeline; external click is separate event.
- GET/POST/PATCH /me/saved-searches — saved filters and alert options.
- GET/POST/DELETE /me/following — company subscriptions with entitlement checks.
- GET/PATCH /me/notifications — inbox and read state.
- POST /listing-reports — bounded abuse reporting; support anonymous reporting when safe.
- POST /billing/webhook — signed, idempotent provider notification; provider-specific path existing may differ.

Avoid building endpoints based only on this list. Find and preserve existing contracts; extend them through versioned schemas and tests.

## Appendix B. Ordered engineering work packages

- 1. Repository and UX inventory — Features primarily covered: All VERIFY items; Deliverable: Route/data-flow map; baseline E2E recordings; Release gate: Inventory reviewed; no guessed bugs.
- 2. Trust and source timestamps — Features primarily covered: Q-01–Q-10, O-02, O-08; Deliverable: Source schema + parser fixtures + accurate cards; Release gate: Old crawl ≠ new posting; closed retries safe.
- 3. Search and eligibility — Features primarily covered: S-01–S-07, S-11; Deliverable: Indexed filter endpoints, clear UI; Release gate: Benchmark precision and filter-state tests pass.
- 4. Auth/profile hardening — Features primarily covered: A-01–A-14, SEC-01–SEC-04; Deliverable: Account/profile regression + private storage; Release gate: Cross-user and OAuth tests pass.
- 5. Notifications core — Features primarily covered: N-03–N-06, N-08, N-10; Deliverable: Idempotent rules, inbox, delivery logs; Release gate: Repeated worker executions never spam.
- 6. Billing and entitlement audit — Features primarily covered: B-01–B-06, B-09; Deliverable: Server-side plan gates + reconciliation; Release gate: Payment replay/failed-webhook tests pass.
- 7. Saved/application workspace — Features primarily covered: T-01–T-09; Deliverable: User-owned worklists and tracker improvements; Release gate: External click never implies Applied.
- 8. Company-follow + saved search — Features primarily covered: C-01–C-04, N-01–N-02; Deliverable: Following feed + alert-rule UI; Release gate: Correct follow/plan-limit behavior.
- 9. Matching explainability — Features primarily covered: R-01–R-07, O-05; Deliverable: Transparent relevance explanations; Release gate: Hard eligibility separated from soft match.
- 10. Category-specialist experiences — Features primarily covered: K-01–K-06; Deliverable: Schemas, filters, cards, calendar; Release gate: Job and scholarship semantics don't mix.
- 11. Accessibility, SEO, performance — Features primarily covered: U-01–U-10; Deliverable: Audited mobile/a11y/SEO releases; Release gate: Core Web Vitals and a11y gates reached.
- 12. Differentiators and growth — Features primarily covered: P2/P3 items; Deliverable: Tested optional features; Release gate: No regression to source-first core.

### Ticket decomposition standard

Every feature from H-01 through FUT-07 should become one parent issue and usually several implementation subtasks:

- Audit existing code and behavior with file/route/API references; mark Already complete, Improve, Missing, or Blocked.
- Reproduce baseline and capture screenshots, logs, fixtures or user journey before editing.
- Describe minimal design (UX states, schema, API, authorization, background job effects).
- Make change in narrow PR; run migrations and backfill in staging; add tests and docs.
- Review regressions and security; complete QA including negative/error/timeout cases.
- Roll out gradually with telemetry, rollback plan and product-owner sign-off.

## Appendix C. Release acceptance matrix / regression scenarios

- QA-01 — New visitor searches without account. Expected outcome: Search and public detail accessible; no surprise payment wall.
- QA-02 — Query with typos and role aliases. Expected outcome: Relevant titles ranked appropriately.
- QA-03 — Student-only filter on known senior roles. Expected outcome: Senior records excluded from eligible results.
- QA-04 — Remote-US-only role viewed from India. Expected outcome: Geographic eligibility shown accurately or Unknown.
- QA-05 — Old posting re-crawled today. Expected outcome: Old source date retained; only last-check timestamp advances.
- QA-06 — Missing compensation and deadline. Expected outcome: Clearly "Not disclosed" or Unknown, never 0 or "Due today".
- QA-07 — Apply click opens employer source. Expected outcome: External link works and tracker is not auto-marked Applied.
- QA-08 — User manually records Applied. Expected outcome: Status persists across refresh/devices and appears in timeline.
- QA-09 — Duplicate source listings refer to one requisition. Expected outcome: One canonical opportunity with traceable source alternatives.
- QA-10 — Similar role titles with different requisitions. Expected outcome: Separate opportunities retained.
- QA-11 — Source returns transient 503/429. Expected outcome: Role is uncertain/retryable, not automatically closed.
- QA-12 — Source explicitly confirms closure. Expected outcome: Active feed excludes role; saved view shows Closed.
- QA-13 — Save double-click, retry and network interruption. Expected outcome: Exactly one saved record with consistent UI.
- QA-14 — Signed-in user changes graduation year. Expected outcome: Preference persists and relevant recommendations recalculate.
- QA-15 — User A requests User B's saved role, resume or receipt. Expected outcome: Denied, with no private data exposure.
- QA-16 — OAuth login interrupted or token expired. Expected outcome: Safe recovery, no redirect loop, no duplicate account.
- QA-17 — Same opportunity ingested 3 times. Expected outcome: One user alert per eligible event despite retries.
- QA-18 — User unsubscribes from digest. Expected outcome: No later non-essential digest to that address.
- QA-19 — User sets quiet hours spanning midnight. Expected outcome: Non-urgent messages delayed per timezone.
- QA-20 — Multiple tabs mark notifications read. Expected outcome: Badge and inbox reach consistent unread count.
- QA-21 — Pro activated by payment webhook. Expected outcome: Plan changes only upon trusted provider confirmation.
- QA-22 — Replayed payment webhook. Expected outcome: No duplicate entitlement or billing record.
- QA-23 — Failed payment or expired one-time pass. Expected outcome: Entitlements gracefully reflect real state.
- QA-24 — User downgrades with extra followed companies. Expected outcome: Existing records preserved; premium actions handled clearly.
- QA-25 — Resume deletion. Expected outcome: File plus derived private data handled per retention policy.
- QA-26 — Expired deadline across India/US DST boundary. Expected outcome: Correct user-local date/time and reminder.
- QA-27 — Mobile 320px width and screen keyboard. Expected outcome: No clipped Apply/Save/filter controls.
- QA-28 — Keyboard-only Search → Detail → Save. Expected outcome: Focus visible, logical and not trapped.
- QA-29 — No results / API timeout / rate limit. Expected outcome: Clear message, retry, current filter state retained.
- QA-30 — Account deletion / export. Expected outcome: Ownership verified and promised actions completed.
- QA-31 — User reports suspicious listing. Expected outcome: Report retained, prioritized and auditable.
- QA-32 — Privacy-sensitive caches across sessions. Expected outcome: User B never receives User A's personalized HTML/data.
- QA-33 — Competitive scholarship with financial eligibility. Expected outcome: Missing criterion shows Unknown; no sensitive guess.
- QA-34 — Country and currency formats across regions. Expected outcome: Source currency and work restriction remain unambiguous.
- QA-35 — Email bounce/provider outage. Expected outcome: Retries bounded and suppression list respected.

## Appendix D. KPIs, alert thresholds and launch decision criteria

Do not set arbitrary success thresholds without baseline data. Instrument first, record two-week baselines where feasible, then agree explicit targets by cohort.

- Valid-apply-link rate — Sampled active roles whose original application URL is reachable and relevant. Why it matters: Trust and completion.
- Source freshness coverage — % active roles verified within defined source SLA. Why it matters: Search credibility.
- Duplicate listing rate — Duplicates per canonical unique role. Why it matters: Feed usefulness.
- Ineligible-result rate — Audited fraction of filtered roles with explicit unmet requirements. Why it matters: Matching correctness.
- Zero-result query rate — Searches returning no results. Why it matters: Search and data gaps.
- Search→detail CTR — Opened relevant listing details / searches. Why it matters: Discovery quality.
- Detail→original Apply click — Source-link clicks / detail views. Why it matters: Actionable interest, not applications.
- Save→self-reported applied — Manually marked Applied / previously saved. Why it matters: Workspace usefulness.
- 7d/30d returning users — Users who return within interval. Why it matters: Retention.
- Alert duplicate rate — Duplicate user-visible alert events / logical triggers. Why it matters: Notification quality.
- Alert relevance feedback — Positive/negative feedback on delivered matches. Why it matters: Alert signal quality.
- Free→Pro conversion — New paid subscriptions / eligible free users. Why it matters: Business viability.
- Charge/entitlement mismatch — Billing cases whose server entitlement differs from provider state. Why it matters: Payment correctness.
- Cost per active paid user — Infra + alert + model + provider cost divided by paid active accounts. Why it matters: Margin sustainability.
- Security/privacy incidents — Confirmed access, retention or disclosure incidents. Why it matters: User protection.

Pre-release gates for P0 changes: correct original-source behavior, safe authorization, passing golden-ingestion fixtures, no repeated alert spam, working rollback, mobile/keyboard journey pass, and reconciliation of billing entitlements where affected.

## Appendix E. Product guardrails and explicit non-goals

- Aspirova does not apply on behalf of a student under its current public product description. A redirect is a source-link click, not submission evidence.
- Don't invent a recruiter inbox or employer-side shortlist statuses until a legitimate integration is established. Preserve self-reported application status as such.
- Don't rewrite an existing feature without inspecting it. Public pages already advertise digest, Pro alert and application-tracking capabilities.
- Don't treat a missed scrape as company closure. Model temporary source errors independently from explicit closed state.
- Don't equate number of listings with relevance. Ineligible and duplicate records can lower perceived value.
- Don't require students to provide CGPA, previous internship or resume merely to browse. Collect only justified data and make optional fields genuinely optional.
- Don't make fees for applying a paid Aspirova feature. A student should be able to reach the original source without a paid subscription.
- Don't publish unverifiable trust badges, AI hiring chances or fabricated stipend values. Unknown is a legitimate state.
- Don't launch a community or employer marketplace without moderation, abuse controls, consent and owner capacity.
- Don't launch wholesale AI features before fixing accuracy and ingestion quality. A polished explanation of wrong data is still wrong.

## Appendix F. Implementation instructions for Claude as architect and Codex as implementer

> Project instruction: Treat this specification as a feature backlog, not an order to implement all items simultaneously. First inspect the repository and deployed behavior. For each feature ID: (1) find existing implementation and document its current status; (2) propose the smallest safe improvement and dependencies; (3) let Codex implement one scoped ticket with tests; (4) have Claude review architecture, code, UX and edge cases; (5) run relevant unit/integration/E2E tests; (6) manually verify production-like behavior in staging; (7) sign off or reopen the ticket. Never assert a bug without reproduction and never overwrite a working flow because a feature was listed here as VERIFY. Protect current subscription and application semantics. Prefer accuracy over speed. Keep a changelog referencing feature IDs and provide source file paths and test commands in every handoff.

Suggested task completion template:

```
Feature ID:
Current behavior (routes, components, APIs, models):
Finding: Already complete / Needs improvement / Missing / Blocked
User-visible problem and reproducible evidence:
Proposed UX states and design:
Database/API/worker changes:
Security, privacy and billing implications:
Edge cases and failure modes:
Automated tests added/updated:
Manual staging test result:
Performance/alert/cost impact:
Rollback procedure:
Reviewer sign-off:
```

## Appendix G. Evidence and external references

Aspirova first-party public pages (consulted 10 November 2026):

- Homepage and browser-visible signed-in UI: https://www.aspirova.org/ — source-first positioning, navigation, For You/Latest, geographic controls, listings, company discovery, Saved, Matches, notification indicator, profile access. Dynamic counts vary by time, sorting and geographic filters.
- FAQ: https://www.aspirova.org/faq — free search/browsing and daily digest; Pro instant alerts, weekly report, more company tracking; sign-in to save/track applications; original-site applications; daily updates; problem reporting; no payment to apply.
- About: https://www.aspirova.org/about — aggregator scope; source-first original links; companies do not directly pay to appear or post on Aspirova.
- Pricing: https://www.aspirova.org/pricing — linked publicly, but full checkout and entitlement flow were not validated here; inspect actual copy before changing plan behavior.
- Example indexed role: https://www.aspirova.org/opportunity/perplexity-sales-onboarding-manager-1144dedc — publicly indexed detailed role pages illustrate why normalization of role category, location and seniority matters.

Public market-context reference:

- Internshala Android app description: https://play.google.com/store/apps/details?id=com.internshala.app — published description of resume builder, advanced filters and instant alerts. The comparison is market context, not an assertion that all competitor behavior has been end-to-end tested.

Evidence limits: Direct web fetches of some authenticated/account routes and the pricing screen were unavailable at audit time. An open signed-in browser tab provided homepage markup, but this does not prove account saving, payment callbacks, email deliverability, notification scheduling or source-crawler operations. These require repository access and controlled E2E testing. Thus every existing-capability claim is restricted to observed or first-party documented features; all deeper implementation recommendations remain specifications.

Document end. Total feature IDs and priorities can be extracted automatically from ### <ID> — headings.
