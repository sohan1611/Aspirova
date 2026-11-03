# ASPIROVA — EXPECTED FEATURES, PROFILE REDESIGN & COMPETITOR GAP

**Research / roadmap date:** 4 November 2026 (IST)  
**Product:** https://www.aspirova.org/  
**Code snapshot:** [`sohan1611/Aspirova@a90c6e1`](https://github.com/sohan1611/Aspirova/tree/a90c6e1918b7145d653593922e81a6d541ab5c41) (3 Nov 2026).  
**Audience:** Students, internship candidates, new graduates and early-career applicants; India-first users with domestic/global ambitions.  
**Scope:** Expected candidate experience, especially **Accounts & Profiles**, then discovery, saves/tracker, alerts, resumes, company follows, trust, billing and privacy.

> **Method:** Compared the actual Aspirova public interface and linked code against recent **official LinkedIn, Wellfound and Simplify help/product documentation**. The comparison is about users' expectations, **not a claim that every competitor feature should be copied**. Unlike Wellfound, Aspirova is an *indexer linking out to third-party sites* rather than a recruiting platform that receives applications. Features requiring recruiter marketplace or browser extensions are labeled optional. Signed-in pages were inspected through source code, not by executing a logged-in production journey.

## Executive view

Aspirova already has considerable infrastructure: email + Google/GitHub authentication, account profile basics, fields/interests onboarding, skills and experience on a resume screen, private PDF storage/ATS estimate, saved opportunities with status stages, saved searches with alerts, followed companies, notification toggles, billing, referrals, personalized feed and reporting. **Do not re-build those as if absent.** The differentiating gaps are a **coherent candidate identity**, transparent cross-device preference syncing, richer *intent* (role, location, eligibility), editable searches and tracker detail, clear direct-source verification, honest freshness, and control over private account data.

**Strategic product position:** “A trustworthy, source-first opportunity finder that remembers who you are and what you want—without making an Aspirova account or subscription necessary merely to open an employer application.” Build better matching and tracking on top of high-quality listings, rather than adding heavy AI before fixing classification, source attribution and account trust.

## 1 — What competitors visibly offer (official sources)

| User expectation | LinkedIn | Wellfound | Simplify | Aspirova snapshot / actual gap |
|---|---|---|---|---|
| Rich work-oriented profile | Job recommendations use profile, education, experience, location and activity [L1] | Skills, work history, education, achievements, public links, locations, desired role [W1] | Experience, education, skills, documents, preferences, profile strength [S2] | **Partial:** name/college/grad year in Account; fields/interests in onboarding; skills/exposure and one resume in Resume check. Need a unified editable dashboard, not assume fields are missing from backend. |
| Target job preferences | Search filters, location, employment type, experience; alerts [L2] | Desired role, remote, location, salary, work authorization, company size [W1] | Role, location and match preferences separate from search [S1] | **Partial:** feed filters and field profile exist; **no account-wide structured target role/location/remote/salary preferences** in examined Account schema. |
| Saved jobs and application tracker | Stages and notes, incl manual updates for off-site applications [L3] | Applications within Wellfound product [W2] | Stages, notes, documents, manual job add/import [S3] | **Partial:** Aspirova already has saved/applied/interview/offer/rejected stages and “Did you apply?”; missing richer record, notes, follow-up date and manually entered external jobs. |
| Saved searches & delivery | Create/manage alerts; edit and choose daily/weekly channel [L4] | Jobs matching profile/preferences [W3] | Saved filters and match preferences [S4] | **Partial:** saves searches, alerts ON/OFF and delete; **cannot edit name/filter params after creation** via the inspected API. |
| Resume/document workspace | Stored resume for native applications [L5] | Resume and portfolio within candidate profile [W1] | Documents workspace, multiple resumes/letters, autofill [S1] | **Partial:** one private PDF, ATS-readiness estimate, skills; AI role-matching explicitly disabled in code. |
| Profile completeness | Profile guidance | Fully filled profile encouraged [W4] | Detailed “Profile Strength” checklist [S2] | **Gap:** current 3-field academic indicator can reach 100% without career preferences/skills/resume. |
| Source and listing transparency | Employers / job poster verification filters [L2] | Direct platform applications and employer context [W3] | Freshness/currency caveats in listing help [S5] | **High-priority defect:** actual aggregator destination can be labeled employer's own page; employment type classification conflates graduates/interns. |
| Privacy & user control | Private preferences and visibility controls [L1] | Optional job profile privacy/visibility controls [W2] | Profile and settings across app [S1] | **Partial:** account settings, local/global sign-out; deletion/export by support email, no self-service controls. |

**Official comparator links (retrieved November 2026)**

- **[L1]** LinkedIn recommendation logic: https://www.linkedin.com/help/linkedin/answer/a512279
- **[L2]** LinkedIn job filters: https://www.linkedin.com/help/linkedin/answer/a507441/filter-and-sort-job-search-results?lang=en
- **[L3]** LinkedIn job tracker, stages and notes: https://www.linkedin.com/help/linkedin/answer/a8684146
- **[L4]** LinkedIn alert frequency and channels: https://www.linkedin.com/help/linkedin/answer/a511279/job-alerts-on-linkedin?lang=en
- **[L5]** LinkedIn applied-job access: https://www.linkedin.com/help/linkedin/answer/a512329/
- **[W1]** Wellfound candidate profile elements: https://help.wellfound.com/article/773-how-do-i-edit-my-candidate-profile
- **[W2]** Wellfound job/public profile visibility differences: https://help.wellfound.com/article/829-how-do-profiles-work-what-is-the-difference-between-a-job-profile-and-public-profile
- **[W3]** Wellfound candidate/product experience: https://wellfound.com/candidates/overview
- **[W4]** Wellfound profile quality guidance: https://help.wellfound.com/article/771-how-can-i-be-featured
- **[S1]** Simplify dashboard, documents and preferences: https://help.simplify.jobs/en/help/articles/6390631-navigate-your-dashboard
- **[S2]** Simplify Profile Strength: https://help.simplify.jobs/help/articles/7361554-build-your-profile-strength
- **[S3]** Simplify job tracker: https://help.simplify.jobs/en/help/articles/2140179-use-the-job-tracker
- **[S4]** Simplify matches vs search: https://help.simplify.jobs/en/help/articles/6542018-job-matches-vs-job-board
- **[S5]** Simplify jobs, currency/recency guidance: https://help.simplify.jobs/en/articles/2830264-view-jobs-on-simplifys-job-board

**Scope guard:** Internshala and Unstop are also relevant to Indian students, and Aspirova already aggregates multiple public career/event sources. This audit did not validate feature-level current Internshala/Unstop account behavior against official documentation, so **no unverified feature comparison with them is asserted**. They should be included in a subsequent supervised visual benchmark.

## 2 — Baseline: features Aspirova ALREADY HAS

| Existing capability | Evidence / nuance | Product action |
|---|---|---|
| Email/password, Google and GitHub sign-in | `frontend/components/AuthWidget.tsx` | **Improve:** privacy-safe signup notice, failure/retry UX, session loading. Do not add redundant auth from scratch. |
| Account settings with sections | `AccountSidebar.tsx` supports Profile, Subscription, Notifications, Saved searches, Security | **Improve:** structure, feedback, unsaved changes and unified career profile. |
| Education basics | `ProfileSection.tsx` name, college, grad year | **Expand:** education history, degree/branch, account geography, expected graduation, eligibility. |
| Stream, specialisation and interests | `OnboardingDialog.tsx` and `ProfileSection.tsx` | **Improve:** edit inline and server sync reliability. |
| Skills and experience/exposure | `ResumeMatchPage.tsx` saves skills and exposure | **Unify:** surface summary/entry within Account; avoid separate “profile” meanings. |
| One private PDF and ATS estimate | `ResumeMatchPage.tsx`, Supabase Storage and `/resume` | **Improve:** versioning, role-specific insight, privacy labels; **AI resume matching currently off**. |
| Saved opportunity list & stages | `/saved`, `BookmarksProvider.tsx`, backend bookmarks API | **Expand:** notes, dates, reminders, archive, external imports. |
| Saved searches and new-match alerts | `SavedSearchesSection.tsx`, backend saved-search API | **Expand:** edit/rename, cadence, quality preview, safe delete. |
| Followed/dream companies | `NotificationsSection.tsx`, backend dream-companies API | **Improve:** follow management and explain alerts/plan limits. |
| Notification control | `NotificationsSection.tsx` | **Fix:** distinguish entitled/on, entitled/off and locked. |
| Subscription cancellation | `SubscriptionSection.tsx`, backend `/subscription/cancel` | **Improve:** invoices, history, retry, clear downgrade consequences. |
| Referrals, report issue, source links | `/referral`, `/report`, `ApplyLink.tsx` | **Improve:** more user-friendly and truthful source status. |

**Do not market as live:** The file `frontend/components/ResumeMatchPage.tsx` has `RESUME_MATCHES_ENABLED = false`. Existing rule-based ATS readiness is not the same as personalized AI job matches. Current frontend pricing feature labels intentionally show only active features; confirm site deployment before new promises.

## 3 — Recommended Accounts & Profiles experience (highest emphasis)

### Proposed information architecture

Keep `/account` but reorganize into a clear **My career profile** area and dedicated controls:

```text
/account
  Overview          completion checklist, alerts & tracker snapshot
  Personal details  display name, avatar, email, country; sign-in identity
  Education         college, branch, degree, graduation year, multiple degrees
  Career goals      internships/jobs, desired roles, domains, work mode, locations
  Skills & projects selected skills, GitHub/portfolio/LinkedIn, achievements
  Resume            one existing PDF now; multi-version workspace later
  Saved & tracker   opportunity/application history, interview/follow-up dates
  Alerts            saved searches, frequency, company follows, quiet hours
  Billing           plan, effective features, renewal, invoices, cancellation
  Security & data   password, providers, sessions, export/delete, consent
```

This is an **information architecture suggestion**, not a claim current tabs are absent. Preserve deep links (`?section=profile`, etc.) or redirect them. On mobile use a labeled settings select or sidebar with back navigation; avoid nested multi-level modals.

### Profile fields worth adding — specific to internship seekers

| Field | Why candidates expect it | Type/privacy | Minimum behavior |
|---|---|---|---|
| Preferred/real display name | More human account identity | User-only | Editable; safe normalization; visible in greeting; no forced legal name |
| Avatar | Recognizable account | Private | OAuth picture plus optional upload/remove; fallback initials |
| Degree, stream/branch, college | Student eligibility | Account | Multi-level selector with custom college and degree; no false mandatory assumptions |
| Start/end year, current year of study | Class-year eligibility | Account | Derived safely from graduation year where appropriate; optional exact dates |
| Target role(s) | Personalize rather than only coarse field | Account | Multi-select roles; distinguish internship/new-grad/full-time |
| Desired location(s) | India vs abroad/remote | Account + device | City/state/country, multiple choices, selected default; clear sync meaning |
| Remote/hybrid/onsite | Critical fit criterion | Account | Multi-select; “remote in my country” distinct from worldwide remote |
| Work authorization / visa need | Overseas eligibility | Sensitive optional | Opt-in only; clear purpose; never infer citizenship from IP |
| Internship duration / availability | Many programmes have months/dates | Account optional | Duration months, earliest start, semester constraints |
| Expected stipend/CTC | Avoid irrelevant roles | Private preference | Range, currency, period (month/year), negotiable toggle |
| Skills + proficiency/evidence | Fit and project matching | Private by default | Skills already saved; add user-verified proficiency and optional source |
| Portfolio, GitHub, LinkedIn links | Show work in a career dashboard | Private by default | Validate URL; preview/visit links; no auto-public profile |
| Projects/achievements | Important with little experience | Account | Simple title, stack, links, measured result; optional |
| Resume versions | Different roles require different CVs | Private storage | One existing initially; later named versions, primary selection, delete |
| Search availability | Avoid irrelevant current postings | Account | Available now, summer, after graduation, flexible |

**Privacy recommendation:** Aspirova is a link-out indexer, **not a recruiter marketplace**. The above is for matching and reducing repeated filters, not to make profile publicly searchable. Default all profile data to private; request only what is useful, optionalize sensitive attributes, and document retention/third parties.

## 4 — Feature specification backlog (with acceptance criteria)

Priority meaning: **Must = launch-quality foundation; Next = retention and everyday usefulness; Later = differentiator only after trust/reliability**. Sizes are directional, not time promises: S = isolated UI/API, M = multi-component, L = data-model/pipeline/migration.

### MUST: First make the existing experience credible

**F-01 [Must, M] — One truthful profile completion hub**  
**User story:** “I want to know what information will improve recommendations, not be told I'm 100% ready because I entered my name and college.”  
**Build:** Split “Academic basics” from “Career readiness”; checklist with Edit links to name, education, interests, roles, skills, resume, optional links. Each item explains why it matters.  
**Acceptance:** Scores scoped by label, resume optional, completion survives re-login, no employability claims or manipulative percentages.  
**Benchmark:** Simplify [S2], Wellfound [W1]. **Bug link:** A-05.

**F-02 [Must, M] — Job intent and preference settings in account**  
**Story:** “Remember I want backend/software internships in Bengaluru or remote, and don't bury me under senior US jobs.”  
**Build:** Multi-role, career stage (intern/new grad/full time), location, remote status, type, stipend or salary, country restrictions; explicit “strict filters” vs “preferences for ranking”. Store server-side for signed-in user, guest-side locally.  
**Acceptance:** Reopens correctly on mobile/second device; user can clear each filter; results explain match; no silently excluding every job.

**F-03 [Must, M] — Consolidated career profile editing**  
**Story:** “I shouldn't hunt across Profile, onboarding modal, Resume check and local device settings to update who I am.”  
**Build:** Inline cards in Account for field/interests, skills, graduation, target roles and country, with links to full resume workspace; preserve existing APIs and data.  
**Acceptance:** No conflicting copies of fields; unsaved changes warn, validation says what failed, save state persists on refresh, loading is correct.

**F-04 [Must, S/M] — Clearly labeled provider / profile actions**  
**Story:** “I know whether my sign-in uses Google, GitHub or email and can manage it safely.”  
**Build:** The existing provider badges become explanation of connected identities, password vs provider sign-in, how to recover; link/unlink **only if verified provider support and reauth**. Add confirmation for password changes and a reliable success/error toast. For a newly authorized Google/GitHub user, offer to use the provider’s display name if supplied rather than starting with a blank name (bug A-17).  
**Acceptance:** Never allow disconnecting last login method without a tested fallback; don't display unavailable controls as functional.

**F-05 [Must, M/L] — Export data and self-service account deletion**  
**Story:** “I can leave the product or get a copy of my records without writing an email.”  
**Build:** Download a JSON/CSV bundle of profile, saved opportunities and searches, company follows and notification preferences; secure deletion with recent reauth, optional reason, subscription handling, resume PDF removal and retention notice. Until implemented, **rename CTA to 'Request deletion'** and track support request.  
**Acceptance:** One account cannot export or delete another; clear retention policy, confirmations, completion receipt and idempotent retries. **Bug link:** A-09.

**F-06 [Must, M] — Honest source labels / direct-employer verification**  
**Story:** “I know before I click whether the destination is the employer's site or a job aggregator.”  
**Build:** Display **Official company careers / ATS / Aggregator / Event organiser / Unverified** with destination domain. Store source provenance and last destination validation.  
**Acceptance:** No `himalayas.app` link labeled “Company's own listing”; unknown source flagged instead of assumed. **Bug link:** D-02.

**F-07 [Must, M/L] — New-grad vs internship distinction**  
**Story:** “I want internships while still studying, and graduate jobs after graduation.”  
**Build:** Separate career-stage and employment-type tags; annotate true requirements based on employer posting, not only a fuzzy title regex.  
**Acceptance:** “Software Engineer, New Grad” is full-time/new graduate; “Software Engineer Intern” is internship; both available as separate filters. **Bug link:** D-01.

**F-08 [Must, S/M] — No forced account to open application**  
**Story:** “I am browsing a job index; I can visit the application link before deciding whether to make an Aspirova profile.”  
**Build:** Open verified external link for guest, offer Save/Track via sign-in separately; clearly indicate application is completed at employer, not Aspirova.  
**Acceptance:** Guest Apply works and accounts protect only personal saved/tracking data. **Bug link:** A-13.

**F-09 [Must, S/M] — Saved search rename/edit and safe delete**  
**Story:** “I can adjust an alert without rebuilding it; deletion is hard to do accidentally.”  
**Build:** Backend PATCH to update saved-search `name` and validated `params` as well as alerts; frontend Edit and cadence options, duplicate-criteria warning, undo/confirmation.  
**Acceptance:** Edit recalculates next matches correctly; alert does not duplicate after rename; invalid filters 422 with clear UI; 25-cap explained, id ownership enforced.

**F-10 [Must, S/M] — Alerts show what can truly be delivered**  
**Story:** “When a toggle is ON, my plan allows it and I know how often to expect emails.”  
**Build:** Locked state separate from disabled, next send/last sent status if available, verify email button, unsubscribe and quiet hours option.  
**Acceptance:** No paid-only ON appearance to free users; opt-out immediately respected; UI and mail queue agree. **Bug link:** A-04.

### NEXT: Become an everyday application companion

**F-11 [Next, M] — Detailed application tracker record**  
**Build:** Extend existing statuses (Saved/Applied/Interviewing/Offer/Rejected) with applied date, interview date, next follow-up, personal notes, response/closed status, optional attached resume reference. Timeline and filter by upcoming actions.  
**Acceptance:** Changes autosave or visibly commit; notes private; status timeline stable; bulk transitions safe. **Benchmark:** LinkedIn [L3], Simplify [S3].

**F-12 [Next, M] — Save jobs from outside Aspirova**  
**Build:** Manually add employer, title, URL, location and stage; optionally paste a link for parsed autofill with user review; no unsupported “applied” auto-claim.  
**Acceptance:** External records coexist with crawled opportunities; can edit/delete; URLs validated; duplicate suggestions shown without forced merge. **Benchmark:** Simplify [S3].

**F-13 [Next, M] — Deadline reminders / calendar integration**  
**Build:** ICS download for known deadlines and interviews, opt-in email/push for deadlines 7/3/1 days before; preserve timezone and show 'deadline not provided' honestly.  
**Acceptance:** No invented closing dates, no reminders for expired/retracted listings; user can stop all reminders, dates respect locale.

**F-14 [Next, M] — Alerts with cadence and preview**  
**Build:** Individual saved-search email instant/daily/weekly when entitled, preview of matching jobs, dedupe by canonical opportunity ID, rate caps/quiet hours.  
**Acceptance:** Same opportunity not spammed by overlapping filters without clear user control; subject states role/company; one-click manage/unsubscribe. **Benchmark:** LinkedIn [L4].

**F-15 [Next, M] — “Why this matches you” explainable ranking**  
**Build:** On personalized feed display **role match, skills overlap, location, internship/new-grad stage, deadline confidence** with concise reasons, not an opaque 90% fit probability.  
**Acceptance:** Users can expand each factor, correct a preference and see result shift; never imply hiring probability. **Benchmark:** Simplify [S4], [S5].

**F-16 [Next, M] — Resume versions and context-specific selection**  
**Build:** Extend one stored PDF to named versions (Backend, Frontend, Data Science, General), one default; associate version with tracked application; allow private preview/download/delete; reject enormous or malicious files.  
**Acceptance:** Replacing one version never overwrites another; no user can access someone else's signed URL; removing a resume updates references gracefully.

**F-17 [Next, M] — Profile import with user verification**  
**Build:** Extract name, education, projects and skills from uploaded CV **on device or by explicit user consent**; show review before writing account fields. Do not silently overwrite college, years or location.  
**Acceptance:** All extracted fields are editable and tagged confidence; no unsupported demographic inference; user can opt out. **Benchmark:** Simplify [S2].

**F-18 [Next, S/M] — Better followed-company experience**  
**Build:** Central “My companies” list with follow/unfollow, direct company careers link, newly added student roles, domain verified status and last checked time. Existing Followed companies in Notifications can deep-link here.  
**Acceptance:** No duplicate aliases, plan limit visible before follow, alerts only from opted-in companies when entitled.

**F-19 [Next, M/L] — Eligibility-focused search**  
**Build:** Filter by **graduation year, current student/new graduate, degree/branch, country eligibility, internship length, stipend** where explicitly extracted; missing data = unknown, not ineligible.  
**Acceptance:** Explain each eligibility flag with quoted/linked employer evidence, distinguish “unknown” from “no,” allow user override.

**F-20 [Next, S/M] — Feed quality controls**  
**Build:** Hide, “not interested,” mute employer, flag wrong type/location/closed listing, and feedback reasons with lightweight blocking of repeat spam.  
**Acceptance:** Hide syncs across devices when signed in, can undo, no silent permanent deletion. Read-only public report issue already exists—reuse it.

**F-21 [Next, S/M] — Transparent verified freshness**  
**Build:** Show `last_checked_at`, `last_seen_at`, `posted_at` separately only when trustworthy; “Checked 4h ago,” “Open status unverified” and source errors.  
**Acceptance:** Never treat crawl time as posting time; flagged expired jobs fall out of active feed after verification; unknown ≠ open.

**F-22 [Next, M] — Better onboarding without sign-up coercion**  
**Build:** 30–60-second optional onboarding asking student year, 1–3 interests, target role/location; skip with generic feed; prompt to save preferences after usefulness demonstrated.  
**Acceptance:** Browsing and Apply are possible without account; all prompts resumable, mobile-friendly and accessible.

**F-23 [Next, S] — Dashboard with meaningful next actions**  
**Build:** Account overview showing saved (strict count), applied, upcoming deadlines, followed company changes and 3 strong recommendations based on existing profile; not generic engagement counters.  
**Acceptance:** Each tile links to exact filtered data; empty states teach first action; consistent with `/saved` API.

### LATER: Differentiate only after listing reliability

**F-24 [Later, L] — Strong, contextual resume-to-job fit**  
**Build:** Job-specific keyword/skills comparison, role requirements and missing-evidence checklist; optionally AI after cost/privacy/consent evaluation. **Do not overpromise AI matching currently disabled.**  
**Acceptance:** Caveat that score estimates coverage, not employer decision; user can view exact matched evidence; no invented skills.

**F-25 [Later, L] — Browser extension to collect external opportunities**  
**Build:** One-click Save to Aspirova from Greenhouse, Lever, Ashby, Workday and general sites with permissions limited to active page.  
**Acceptance:** Clear opt-in permissions, user verifies title/company/URL, no application submitted by Aspirova. **Benchmark:** Simplify offers browser Copilot; not required for current product.

**F-26 [Later, M] — Interview preparation tied to tracker**  
**Build:** Private notes, role-specific company research from verifiable public sources, question checklist and interview reminders; optional mock-interview practice.  
**Acceptance:** No unverified company claims; user can erase data; avoids implying recruiter integration.

**F-27 [Later, M] — Personalized weekly career digest**  
**Build:** Existing weekly report capability enriched with applications tracked, new opportunities by field, deadlines and actionable recommendations.  
**Acceptance:** Summarizes actual account data, does not hallucinate applications, respects plan and preference, no PII in email subject.

**F-28 [Later, M] — Student opportunity calendar and programme watchlist**  
**Build:** Annual recurring research programmes/scholarships plus application periods labeled as **expected**, **confirmed open**, **closed**, with history.  
**Acceptance:** A prior-year estimate never labeled live; reminders only when opted in; verified source attached.

**F-29 [Later, M] — Trust and safety scorecard (internal, not bogus public rating)**  
**Build:** Per-source completeness, link-resolve success, stale-posting rate, category precision, company alias collision rate, report turnaround.  
**Acceptance:** Report real denominator, samples and unknowns; alert engineers on material regressions. Only surface public verification badges when evidence is sufficient.

**F-30 [Later, L] — Optional multi-surface experience**  
**Build:** PWA/install and browser notifications **only when alert reliability is established**. Native mobile app should not precede responsive web reliability.  
**Acceptance:** Offline-state copy correct, push opt-in revocable, no duplicates across devices, accessible and battery-friendly.

## 5 — Core account journeys to implement and audit

| Journey | Current state from source | Target flow | Failure conditions to test |
|---|---|---|---|
| First visit | Generic public feed, sign-in modals and onboarding | Explore first → set optional goals → save only when useful | Hard back, expired link, no cookies/storage, slow network |
| Email signup | Email/password plus reset, OAuth | Safe signup notices → verify email → preserve prior action → Profile checklist | Existing account privacy, duplicate identities, retry after failed network |
| Google/GitHub login | Provider OAuth exists | Single identity, correct return URL, robust provider failure recovery | Cancel, denied consent, existing password account, wrong provider |
| Profile save | Three core fields; field/interest modal | One-account profile section with inline edit and unsaved-change protection | Concurrent tabs, server error, different device, invalid college |
| Preferences | Field interests server-synced; country local-only | Explicit search preferences synced to account, device browsing country labeled | Country changes, migration, local storage blocked, expired session |
| Skills/resume | Skills, exposure and one PDF on Resume check | Clear Profile link, private file preview, resume versions eventually | Two-account access, overwrite, save metadata failure, file deletion |
| Saved searches | Create, toggle alerts, delete | Edit filters, change frequency, rename, preview and undo | Limit 25, duplicate matching, undo-after-refresh |
| Company follow | Followed companies visible | My companies + source verified labels + alert scope | Unfollow during send, plan downgrade, alias duplicate |
| Billing | Subscription and cancellation present | Transparent plan, invoices and effective date, support/reconciliation | Duplicate webhook, cancellation, expiry, currency vs country mismatch |
| Account deletion | Support email only | In-app request now, self-serve export/deletion when ready | Active subscription, reauth, stale sessions, resume files, backups |

### Recommended Profile UI copy examples

- **Basics:** “Academic profile · 3 of 3 complete” rather than “Your entire profile is complete.”
- **Career goals:** “What kind of opportunities are you looking for?” with chips for Internship, Graduate Role, Full-time Job, Hackathon and Scholarship.
- **Geography:** “Preferred locations (syncs to your Aspirova account)” and separate “Browse country (this device only)” until sync work is done.
- **Remote:** “Remote — open to applicants in India” is **not** the same as “Remote — worldwide.”
- **Resume:** “ATS readiness estimate — checks formatting/content signals, not your odds of being hired.”
- **External Apply:** “Apply on SemiAnalysis via Himalayas” when only aggregator link is verified; do not claim direct employer.
- **Account data:** “Request account deletion” if support must act; show case ID and expected next step.

## 6 — Data model & privacy design notes

**Avoid putting all fields into one fragile JSON blob.** The existing `AccountUpdate` supports `display_name`, `college`, `graduation_year`, `field_profile`, `skills`, `exposure`, `resume`, and `notification_prefs`. Add versioned, validated typed fields or clearly typed related tables for:

1. `career_preferences`: desired career stages, role taxonomy IDs, country/city choices, work mode, salary range with currency/period, availability and privacy consent.
2. `education_entries`: institution ID/free-text, country, degree, branch, start/end/graduation and `is_current`, with migration from single college/year.
3. `portfolio_links` and `project_entries`: user-owned URL/title/description; optional, private.
4. `application_events`: bookmark ID, stage transitions, notes, applied date, follow-up reminder and optional resume-version ID; separate observed vs self-reported status.
5. `saved_searches`: editable validated `name`, filters and alert cadence with explicit `last_alerted_at`/`last_checked_at` and dedupe keys.
6. `resume_versions`: owned storage paths, file hash, uploaded timestamp, score algorithm version, safe file state machine and cleanup marker.
7. `account_privacy_requests`: export/deletion request with consent and state transitions; minimize personal data in logs.

**Migration rules:** No silent overwriting of existing field profile, local country or resume. Derive from explicit choices where possible, offer one-time review, and retain backward compatibility. Every private model query must be scoped by authenticated user ID. Verify RLS for Supabase storage, file-size/type checks, URL safety, PII retention, deletion handling and signed URL TTL. External employer applications remain at employer sites; do not store application form credentials or contents.

## 7 — Release roadmap and metrics

### Phase A — Trust and account correctness first

Fix the companion bug report's **A-01, A-02, D-01, D-02, A-03, A-04** before adding new tiers. Deliver F-01, F-06, F-07, F-09 and clear guest Apply policy (F-08). Validate on a pinned staging build. Establish **category classification precision**, **direct-link label accuracy**, **signup completion rate**, **auth error rate**, **profile form save success**, **alert expectation mismatch**. All metrics must include denominators/time window and source samples.

### Phase B — Account usefulness and retention

Ship F-02, F-03, F-05 (request/export path), F-10, F-11, F-14, F-18, F-22, F-23. Prioritize one coherent profile and application tracker before multiple AI features. Watch **percentage of users choosing target roles**, **saved opportunities with stage updates**, **return visits within 7/30 days**, **number of legitimate alert opens**, **user-reported misleading source links**. Do not optimize vanity clicks on Apply as a substitute for successful external applications.

### Phase C — Higher-value personalization

Extend eligibility filters F-19, resume workflow F-16/17 and explainable match reasons F-15, then optionally F-24+ if costs/privacy justified. Validate **user-ranked relevance on a labeled sample** rather than asserting a made-up fit percentage.

### Priority decision table

| Deliverable | Why now | Relative effort | Dependency |
|---|---|---|---|
| Secure signup notices + initial user upsert | Privacy + reliability | S/M | Existing auth path |
| Correct new-grad classification, backfill, tests | Search results and alerts currently wrong | M | Pipeline and migration |
| Verified source type and destination | Founder promise & trust | M | Provenance columns, URL verification |
| Account profile hub + honest completion | Candidate expectation and personalization | M | Existing profile APIs |
| Job preferences synced across devices | Relevance / retention | M/L | New typed fields, filter mapping |
| Saved-search edit + delete undo | Existing workflow feels incomplete | S/M | Backend CRUD extension |
| Detailed tracker / private notes / reminders | Regular repeat visits | M | Application events |
| Privacy data export/deletion | User confidence | M/L | Auth, storage and subscription lifecycle |
| Multi-resume / AI job matching | Differentiation, not first fix | L | Clean profile, consent, private storage and label integrity |

## 8 — Suggested acceptance standards for Claude/Codex implementation

A feature is **not finished** merely because lint/typecheck/build succeed. For every feature, the implementer should supply:

- **Before/after behavior** on the relevant UI route, with screenshot or reproducible page trace on mobile and desktop.
- **API validation and ownership tests**, including another user's ID, missing data, invalid payload, network failure and retry.
- **Data migration test** preserving existing profile, saved searches, billing and resume metadata; rollback plan for schema changes.
- **Accessibility**: keyboard focus after dialog open/close, labeled form errors, 200% zoom, screen-reader switch descriptions and 44px touch targets where possible.
- **Plan and email entitlement truth**: free vs paid, cancellation, upgrade/downgrade, opt-out, unsubscribed delivery and provider failure.
- **Real source/data sample** with counts. For classification and source provenance, check a representative set from different providers; keep false-positive/negative examples in fixtures.
- **Privacy**: data minimization, explicit opt-in for sensitive fields, storage RLS, no unowned file access, deletion and export handling.
- **Deployment verification**: read-only smoke against actual served pages at the deployed commit, not an assertion based solely on unit tests.

## 9 — What NOT to prioritize yet

Do not rush a recruiter-facing public profile, employer messaging, native in-site apply workflow, application auto-submit agent, heavy ATS score “hire probability,” or expensive AI features before fixing source labels and role classification. Wellfound's one-click applications and recruiter discovery depend on a different marketplace model. Simplify's browser Copilot/Autopilot are substantial separate products, not basic missing account buttons. Aspirova's credible near-term advantage is *verified coverage, reliable alerts, relevant search and private candidate tracking*.

## 10 — Sources and audit limits

**Aspirova:** https://www.aspirova.org/ ; https://www.aspirova.org/about ; https://www.aspirova.org/faq ; https://www.aspirova.org/privacy ; https://www.aspirova.org/opportunity/semianalysis-research-intern-eu-a319167f ; https://www.aspirova.org/opportunity/stripe-software-engineer-new-grad-3e02d435 ; https://github.com/sohan1611/Aspirova/tree/a90c6e1918b7145d653593922e81a6d541ab5c41.

**Competitors:** Official LinkedIn Help, Wellfound Support and Simplify Help pages linked individually in §1. Sites update; reconfirm before copy/design decisions. This document is a **feature and user-expectation research backlog**, not results of logged-in execution. See `Aspirova_Bug_Audit_and_Fixes.md` for severity-ranked defects, evidence, reproduction steps, and quality-assurance test matrix.
