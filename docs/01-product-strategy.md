# 01 — Product Strategy

*Author: Chief Product Officer. Posture: founder-brutal. Nothing here is flattery.*

---

## 1. Vision

**Aspirova is the "never miss an opportunity" layer for ambitious students.**

Students lose opportunities not because they're unqualified, but because opportunities are **scattered, time-boxed, and invisible** — spread across 20+ sites, each with its own deadline, many never surfaced by the big aggregators at all (research lab pages, university portals, GitHub programs, ambassador schemes). The student's real enemy is **information asymmetry + deadlines**.

Aspirova collapses the entire opportunity surface into **one continuously-refreshed, deduplicated, deadline-aware feed**, then layers intelligence on top: "which of these fit *me*, and what should I do about them?"

The 3-year vision: Aspirova becomes the **default career operating system** a student opens every morning — the way they check Instagram, they check Aspirova for "what opened, what's closing, what fits me."

---

## 2. The problem, stated precisely

| Pain | Today's reality | Aspirova's answer |
|------|-----------------|-------------------|
| Fragmentation | 20+ sources, no single view | One normalized feed |
| Deadlines | Missed silently | Deadline heatmap + alerts |
| Hidden opps | Research labs, ambassador programs never aggregated | Tier-3 crawlers + "Hidden Opportunities" |
| Relevance | Generic listings; "is this for me?" | Resume Match + personalization |
| Overwhelm | 100s of listings, no guidance | AI Copilot + roadmap |
| Recurring programs | "When does Google STEP open again?" | Reopen prediction |

---

## 3. Market analysis

- **TAM (India, the wedge):** ~40M+ college students; the realistically reachable, English-comfortable, internship-seeking, smartphone-first segment is in the **single-digit millions** and concentrated in Tier-1/Tier-2 engineering, management, design, and research tracks.
- **SAM (initial beachhead):** ambitious students at competitive colleges who already chase internships/hackathons/fellowships actively — the people who *feel the pain of missing out*. Start here; they are early adopters and natural evangelists.
- **Willingness to pay:** low absolute, but real for a tool that demonstrably lands an internship. ₹49/month is "less than one coffee." The barrier isn't price — it's **proving value fast enough to convert before churn.**
- **Market direction:** opportunity discovery is fragmenting *further* (more platforms, more programs), which makes an aggregation+intelligence layer *more* valuable over time, not less. Tailwind is real.

**Brutal note:** The Indian student market is price-sensitive and notoriously hard to monetize directly. Every consumer-edu founder underestimates this. Your moat is *not* price; it's **comprehensiveness of discovery** (especially the long-tail hidden opps nobody else aggregates) plus **personalization quality.**

---

## 4. Competitor analysis

| Competitor | What they are | Where they're weak (your wedge) |
|------------|---------------|---------------------------------|
| **Internshala** | Marketplace; employers post | Walled garden — only listings *they* host; no aggregation of the wider web; ad-heavy; no real personalization |
| **Unstop (D2C)** | Competitions/hackathons + jobs | Same walled-garden limit; gamified but noisy |
| **LinkedIn** | Professional network + jobs | Overwhelming, not student-first, no deadline intelligence, terrible at hidden/program opps |
| **Wellfound** | Startup jobs | Startup-only, US-centric, not student-internship-focused |
| **College placement cells** | Offline + spreadsheets | Manual, slow, only *their* tie-up companies |
| **WhatsApp/Telegram groups** | Word-of-mouth opp sharing | This is your **real competitor** — free, fast, social. You must be *better than the group chat.* |

**The single most important competitive insight:** Your true competitor is not Internshala — it's the **chaotic free Telegram/WhatsApp groups** students already use. They are free, social, and "good enough." Aspirova wins only by being **comprehensive + deduplicated + personalized + reliable** in a way a human-run group chat can never be. If Aspirova feels like "a slightly nicer listings site," it loses to the group chat. If it feels like "a system that *catches everything and tells me what's for me*," it wins.

**Aggregation defensibility:** Anyone can copy a feature. The hard-to-copy asset is the **breadth + freshness + dedup quality of the opportunity graph** (Doc 03), built from hundreds of source adapters (Doc 04). That's a compounding data moat a solo competitor can't replicate in a weekend.

---

## 5. User personas

1. **"The Maximizer" — Aarav, 2nd-year CSE.** Already applies to everything; terrified of missing out. *Primary paying persona.* Wants: completeness, instant alerts on dream companies, "did I miss anything?" Converts to Pro fastest.
2. **"The Aspirant" — Diya, 3rd-year, non-CS, wants into product/design.** Doesn't know where to look. Needs *guidance*, not just listings. Values Copilot + Resume Match + roadmap. High Pro value, slower to discover the product.
3. **"The Researcher" — Kabir, final-year, wants research internships/fellowships.** Hunts the long tail (labs, ambassador programs, GitHub). Aspirova's Tier-3 crawlers are *uniquely* valuable to him; almost nobody else aggregates this. High loyalty, evangelist.
4. **"The Casual" — Sneha, 1st-year.** Browses occasionally. **Stays free forever** — and that's fine; she's acquisition fuel, future converter, and a referral node.
5. **"The Placement Coordinator" — future B2B persona.** A college's training-and-placement officer who'd pay for a campus-wide license. *Your real margin lever* (Doc 06).

---

## 6. Unique advantages (the moat, ranked)

1. **Long-tail discovery (Tier-3).** Research labs, ambassador programs, GitHub opportunities, niche fellowships — the stuff *no aggregator covers* because it's not commercially worth their while. For Aspirova it's cheap (24h crawl) and *uniquely* valuable. This is the most defensible, least-copyable asset.
2. **ATS-direct freshness.** Pulling Greenhouse/Lever/Ashby boards means Aspirova often surfaces a role *before* it reaches Internshala. "First to know" is the entire product promise.
3. **Deduplicated, normalized opportunity graph.** One canonical record per real opportunity, with every source linked. Nobody offers this clean a view.
4. **Personalization at near-zero marginal cost** (shared embeddings, Doc 05).
5. **Student-built authenticity + campus distribution.** A student founder with campus ambassador reach has a *free, trusted* distribution channel incumbents can't buy cheaply.

---

## 7. Risks (ranked by existential severity)

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | **Legal/ToS — scraping aggregators (Internshala/Unstop/Wellfound/LinkedIn)** | **Existential** | ATS-first strategy (Doc 04). Treat aggregators as best-effort, respect robots.txt, link out rather than republish full content, be ready to drop any source on notice. Never present scraped content as your own original listing. |
| R2 | **Low paid conversion → unsustainable** | High | Annual prepay, indispensable Pro features, B2B + secondary revenue (Doc 06) |
| R3 | **Crawler fragility — sites change, break adapters** | High | Adapter abstraction + change detection + alerting; ATS endpoints are far more stable than HTML scraping |
| R4 | **Solo-founder bandwidth / bus factor** | High | Ruthless scope control (Doc 07), automation-first, this canon so a coding agent can carry load |
| R5 | **Data quality (dupes, dead links, wrong deadlines) erodes trust** | High | Dedup engine + freshness checks + "report this listing"; trust is the whole product |
| R6 | **Notification fatigue → churn** | Medium | Digest batching, smart frequency caps, user-controlled cadence |
| R7 | **Cost creep at scale (email + AI)** | Medium | Shared-AI architecture, SES, batching (Doc 05/06) |
| R8 | **Incumbent copies the feature** | Low–Med | Moat is data breadth + dedup, not features |

**On R1, the honest founder stance:** Aspirova should publicly position as a *discovery and indexing* service that **links users to the original source** (like a search engine), not a re-publisher. Index metadata + link out; don't mirror full proprietary content. Respect `robots.txt`. Prefer official/structured endpoints. Maintain a documented takedown-response process. This is both the ethical and the legally-defensible posture. Get this right early — it's cheaper than a cease-and-desist later. (Not legal advice; consult a lawyer before scaling paid.)

---

## 8. Growth strategy

**Phase A — Beachhead (0 → 2,000 users): own a few campuses.**
- Launch where the founder has reach. Saturate 2–3 colleges before widening.
- Campus ambassadors (free Pro + leaderboard/credit) — your zero-CAC engine.
- Seed the "hidden opportunities" angle hard; it's the share-worthy hook.

**Phase B — Wedge expansion (2k → 25k): adjacent campuses + organic.**
- SEO: every opportunity gets a clean, indexable public page (Next.js SSR). Long-tail "X internship 2026 last date" queries are huge free traffic. This compounds.
- Referral loop (below).

**Phase C — Category (25k+): the default career OS + B2B.**
- Campus B2B licenses; brand partnerships; ethical sponsored placements.

---

## 9. Viral loops (designed, not hoped-for)

1. **Missed-opportunity FOMO loop.** "3 of your friends are tracking Google STEP — it closes in 4 days." Social proof + deadline urgency = shares. The product's core emotion (FOMO) *is* its growth engine.
2. **Referral-for-Pro loop.** "Invite 3 friends → 1 month Pro free." Cheap (you're giving away near-zero-marginal-cost AI), and it targets exactly the high-intent users.
3. **Shareable artifacts.** Weekly Career Report and "opportunities matched to you" are screenshot-worthy. Add a subtle Aspirova watermark/link.
4. **Public opportunity pages.** Every SEO page is a viral surface — a student shares the link in their group chat, the group lands on Aspirova, not the group chat. *This is how you beat the Telegram group: become the link they paste into it.*
5. **Ambassador leaderboard.** Gamified campus competition for sign-ups.

**Loop math discipline:** track viral coefficient `k = invites_sent × conversion_rate`. Target `k > 0.5` early (halving CAC), aspire to `k → 1`. If a loop doesn't move `k`, kill it.

---

## 10. Monetization (strategy; numbers in Doc 06)

- **Freemium with a sharp value wall.** Free is genuinely useful (acquisition + SEO + referral fuel) but deliberately *incomplete* on the two things power-users crave: **instant dream-company alerts** and **personalization (Match/Copilot)**.
- **Decoy pricing.** Pro Lite (₹39) exists to make Pro (₹49) look obviously correct — ₹10 more buys the AI features. Expect most payers on Pro. Don't over-invest in Pro Lite.
- **Annual plans (₹399 Pro Lite / ₹499 Pro, ~15% off)** are the default offer — better cash, lower churn (Doc 06).
- **Annual prepay as the default offer** (Doc 06) — better cash, lower churn, lower transaction cost.
- **Secondary revenue, planned early:** B2B campus licenses (the margin maker), ethical clearly-labeled sponsored opportunities, affiliate referrals (resume tools, courses). Never let sponsored content pollute the trust of the core feed.

**The monetization truth:** at ₹39/₹49, B2C subscriptions break even around ~1,000 users and turn a modest profit beyond that (Doc 06) — viable, but thin. It mainly buys you users and data. The *scalable profit* engine is B2B campus licenses + secondary revenue layered on top of the user base and data moat the B2C engine builds. Architect for both from the start.

---

## 11. Assumptions challenged (the part the founder must not skip)

- ❌ *"Students will pay for a listings aggregator."* → Mostly no. They'll pay for **personalization + not missing dream-company deadlines.** Price the *intelligence*, give away the *listings.*
- ❌ *"We'll crawl Internshala/Unstop/LinkedIn for our data."* → Legally and technically fragile. **ATS-direct is the foundation.** (Doc 04.)
- ❌ *"Internship Prediction Engine"* (predicting if a student gets in) → low-value, high-effort, easily wrong, erodes trust when wrong. **Reframe** to *recurring-program reopen prediction* ("Google STEP usually opens ~November") — a cheap, data-driven, genuinely useful feature. (Doc 05.)
- ❌ *"More notifications = more value."* → No. **Notification fatigue is a top churn driver.** Fewer, smarter, user-controlled.
- ❌ *"₹39 and ₹49 are two real products."* → No. Pro Lite (₹39) is a **decoy.** Own that on purpose.
- ✅ *"Crawl once, store centrally, serve many."* → Correct, and the single best instinct in the brief. Extend it to AI (Doc 05).

---

## HANDOFF TO ENGINEERING

**You are building a discovery + intelligence product, not a job board. Internalize these constraints:**

1. **Every opportunity must have a clean, SSR, SEO-indexable public page** (`/opportunity/{slug}`). This is a growth surface, not just a detail view. Server-render title, company, deadline, normalized description, and a clear "Apply at source" outbound link. Build it canonical-record-first (Doc 03).
2. **Free vs paid gating is config-driven, not hardcoded.** A single `plan_features` config maps plan → feature flags (dream-company limit, instant vs digest alerts, hidden-opps access, Copilot, Match). Never scatter `if plan == 'pro'` across the codebase. (See Doc 08.)
3. **Build the FOMO/deadline mechanics as first-class:** deadline heatmap, "closing soon," "N students tracking this." These are growth features, not cosmetics.
4. **Referral system is Phase-2, but design the schema for it now** (`referrals`, `referral_credits`) so it's not a retrofit. (Doc 03.)
5. **Outbound links, not content mirroring.** Store and display metadata + a normalized summary (Doc 05), but the primary CTA always links to the original source. This is a product *and* legal requirement (R1).
6. **Do not build the "predict if a student gets in" engine.** Build the recurring-reopen feature per Doc 05 instead.
7. **Instrument the viral loops:** emit events for `invite_sent`, `invite_accepted`, `share_clicked` from day one so we can measure `k` (Doc 03 events).

**Definition of done for the product layer:** a student can land on a shared opportunity page from a group chat, sign up in <30s, immediately see a personalized "matches for you" teaser (free preview), and hit a clear, honest paywall for instant alerts + full personalization.
