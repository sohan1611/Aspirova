# 03 — Data Architecture

*Author: Chief Data Architect. The schema below is the canonical data model. Engineers implement migrations from it; deviations require an amendment.*

---

## 1. Modeling philosophy

- **The canonical opportunity is the center of the universe.** Everything links to it. Multiple *raw listings* from multiple *sources* collapse into **one** `opportunities` row. This is what makes the dedup promise (Doc 01) real.
- **Separate raw from canonical.** `raw_listings` preserves exactly what we crawled (audit, reprocessing, dedup evidence). `opportunities` is the clean, user-facing truth. Never overwrite raw with cleaned data.
- **Enrichment is stored, not recomputed.** Summaries, tags, embeddings live in columns/tables and are written once (Doc 05).
- **Events are append-only and partitioned.** User behavior is high-volume; isolate it so it never bloats the transactional tables.
- **Index for the read path we actually serve** (feed filters, FTS, deadline sort, vector match), nothing speculative.

---

## 2. Entity-relationship overview (text)

```
sources ─────┐
             │ 1:N
             ▼
        raw_listings ──N:1──► opportunities ──1:N──► opportunity_sources ──N:1──► sources
                                   │  ▲                                              
            companies ──1:N───────┘  │                                              
                                     │ 1:N                                          
                       opportunity_tags ──N:1──► tags                              
                                     │                                              
                       opportunity_embeddings (1:1, pgvector)                      
                                                                                    
users ──1:N──► subscriptions ──N:1──► plans                                        
  │  ├─1:N──► dream_companies ──N:1──► companies                                   
  │  ├─1:N──► bookmarks ──N:1──► opportunities                                     
  │  ├─1:1──► resume_profiles (embedding)                                          
  │  ├─1:N──► notifications                                                        
  │  ├─1:N──► referrals (as referrer)                                             
  │  └─1:N──► user_events (partitioned)                                            

crawl_runs ──1:N──► crawl_jobs        source_state (change-detection hashes)       
```

---

## 3. Core tables (canonical DDL intent)

> Notation is illustrative SQL the engineer adapts into real migrations (Alembic/SQL). Types target Postgres.

### 3.1 `sources` — the platforms/sites we crawl
```sql
sources (
  id              bigserial PK,
  slug            text UNIQUE,          -- 'greenhouse', 'lever', 'internshala', 'mit-careers'
  name            text,
  type            text,                 -- 'ats' | 'aggregator' | 'university' | 'lab' | 'hackathon' | 'ambassador' | 'github'
  base_url        text,
  crawl_tier      smallint,             -- 1 | 2 | 3  (Doc 04)
  adapter_key     text,                 -- which adapter class handles it
  robots_policy   text,                 -- 'respect' (default) | 'api'
  enabled         boolean DEFAULT true,
  legal_status    text DEFAULT 'ok',    -- 'ok' | 'best_effort' | 'paused' (takedown response)
  created_at      timestamptz DEFAULT now()
)
```

### 3.2 `companies` — normalized canonical companies
```sql
companies (
  id              bigserial PK,
  slug            text UNIQUE,
  name            text NOT NULL,
  name_normalized text,                 -- lowercased, legal-suffix-stripped, for matching
  domain          text,                 -- canonical domain, strong dedup signal
  ats_type        text,                 -- 'greenhouse'|'lever'|'ashby'|'workday'|null
  ats_board_id    text,                 -- the company's board token on that ATS
  logo_url        text,
  is_dream_eligible boolean DEFAULT true,
  created_at      timestamptz DEFAULT now()
)
-- INDEX gin (name_normalized gin_trgm_ops);  UNIQUE(domain) where domain not null
```

### 3.3 `raw_listings` — exactly what we crawled (audit + reprocess + dedup evidence)
```sql
raw_listings (
  id              bigserial PK,
  source_id       bigint FK -> sources,
  source_url      text,                 -- the original listing URL (outbound link)
  external_id     text,                 -- source's own id if available
  content_hash    text,                 -- hash of raw payload for change detection
  raw_payload     jsonb,                -- full scraped/structured blob
  crawled_at      timestamptz DEFAULT now(),
  processed       boolean DEFAULT false,
  opportunity_id  bigint FK -> opportunities NULL  -- set after canonicalization
)
-- INDEX (source_id, external_id);  INDEX (processed) WHERE processed = false;
-- UNIQUE (source_id, external_id) where external_id not null
```

### 3.4 `opportunities` — THE canonical, user-facing record
```sql
opportunities (
  id                bigserial PK,
  slug              text UNIQUE,        -- SEO URL: /opportunity/{slug}
  company_id        bigint FK -> companies NULL,
  title             text NOT NULL,
  title_normalized  text,               -- for dedup/match
  category          text,               -- 'internship'|'hackathon'|'fellowship'|'ambassador'|'research'|'job'
  location          text,
  is_remote         boolean,
  description_raw   text,               -- cleaned but full text (for FTS + summary input)
  summary           text,               -- AI summary, generated ONCE (Doc 05)
  apply_url         text NOT NULL,      -- canonical outbound apply link
  posted_at         timestamptz,
  deadline          timestamptz NULL,   -- nullable: many have no explicit deadline
  deadline_confidence text,             -- 'explicit'|'inferred'|'unknown'
  is_hidden         boolean DEFAULT false,  -- long-tail / premium-visibility flag
  status            text DEFAULT 'active', -- 'active'|'expired'|'filled'|'dead_link'
  first_seen_at     timestamptz DEFAULT now(),
  last_seen_at      timestamptz DEFAULT now(),  -- freshness; if not seen in N crawls -> expire
  search_tsv        tsvector,           -- generated: title + company + summary + tags
  created_at        timestamptz DEFAULT now(),
  updated_at        timestamptz DEFAULT now()
)
```

### 3.5 `opportunity_sources` — every place this canonical opp was found (dedup made visible)
```sql
opportunity_sources (
  id              bigserial PK,
  opportunity_id  bigint FK -> opportunities,
  source_id       bigint FK -> sources,
  source_url      text,
  raw_listing_id  bigint FK -> raw_listings,
  is_primary      boolean DEFAULT false,  -- which source we treat as canonical
  seen_at         timestamptz DEFAULT now(),
  UNIQUE (opportunity_id, source_id, source_url)
)
```
> This table is the payoff of dedup: "found on company page + Internshala + Unstop" → one opp, three rows here.

### 3.6 `tags` + `opportunity_tags` — normalized skills/domains
```sql
tags (id bigserial PK, slug text UNIQUE, label text, kind text)  -- kind: 'skill'|'domain'|'role'|'program'
opportunity_tags (opportunity_id FK, tag_id FK, PK(opportunity_id, tag_id))
```

### 3.7 `opportunity_embeddings` — semantic vectors (pgvector)
```sql
opportunity_embeddings (
  opportunity_id  bigint PK FK -> opportunities,
  embedding       vector(N),            -- N = chosen model dim (e.g., 1024/1536)
  model           text,                 -- track model version for re-embed migrations
  embedded_at     timestamptz DEFAULT now()
)
-- INDEX USING hnsw (embedding vector_cosine_ops);
```

---

## 4. User-domain tables

### 4.1 `users`, `plans`, `subscriptions`
```sql
users (
  id            uuid PK,                -- from Supabase Auth
  email         citext UNIQUE,
  display_name  text,
  college       text,                   -- for B2B + cohort analytics
  graduation_year smallint,
  created_at    timestamptz DEFAULT now(),
  referred_by   uuid FK -> users NULL
)

plans (
  id          smallserial PK,
  key         text UNIQUE,              -- 'free'|'pro_lite_monthly'|'pro_lite_annual'|'pro_monthly'|'pro_annual'
  price_paise integer,                  -- store in PAISE to avoid float errors (Doc 06 §1)
  billing     text,                     -- 'monthly'|'annual'
  features    jsonb                     -- the single source of feature gating (Doc 02 §HANDOFF)
)
-- SEED (canonical, Doc 06 §1):
--   free               | 0      | -        |
--   pro_lite_monthly   | 3900   | monthly  |  (₹39/mo)
--   pro_lite_annual    | 39900  | annual   |  (₹399/yr — saves ₹69, ~15% off)
--   pro_monthly        | 4900   | monthly  |  (₹49/mo)
--   pro_annual         | 49900  | annual   |  (₹499/yr — saves ₹89, ~15% off)
-- Annual is the default highlighted checkout option.

subscriptions (
  id            bigserial PK,
  user_id       uuid FK -> users,
  plan_id       smallint FK -> plans,
  status        text,                   -- 'active'|'past_due'|'canceled'|'trialing'
  razorpay_sub_id text,
  current_period_end timestamptz,
  created_at    timestamptz DEFAULT now()
)
-- INDEX (user_id, status);
```
> **Feature gating lives in `plans.features` (jsonb).** Example: `{"dream_companies": 5, "instant_alerts": true, "copilot": false, "resume_match": false, "hidden_opps": true}`. The app reads this; it never hardcodes plan logic. Changing a plan = changing one row.

### 4.2 `dream_companies`, `bookmarks`, `resume_profiles`
```sql
dream_companies (
  id bigserial PK, user_id uuid FK, company_id bigint FK,
  created_at timestamptz DEFAULT now(),
  UNIQUE(user_id, company_id)
)
bookmarks (
  user_id uuid FK, opportunity_id bigint FK,
  created_at timestamptz DEFAULT now(), PK(user_id, opportunity_id)
)
resume_profiles (
  user_id      uuid PK FK -> users,
  resume_text  text,                    -- parsed text
  embedding    vector(N),               -- embed ONCE per resume version
  parsed_skills jsonb,
  version       integer DEFAULT 1,      -- bump on re-upload -> invalidates cached matches
  updated_at   timestamptz DEFAULT now()
)
```

### 4.3 `notifications` — log + dedup of what we sent
```sql
notifications (
  id            bigserial PK,
  user_id       uuid FK,
  type          text,                   -- 'digest'|'instant_alert'|'weekly_report'|'deadline'
  opportunity_id bigint FK NULL,
  channel       text DEFAULT 'email',
  status        text,                   -- 'queued'|'sent'|'bounced'|'failed'
  sent_at       timestamptz,
  meta          jsonb
)
-- INDEX (user_id, type, sent_at);  used to enforce frequency caps + avoid dupes
```

### 4.4 `referrals` (schema now, feature later — per Doc 01)
```sql
referrals (
  id bigserial PK, referrer_id uuid FK, referred_email citext,
  referred_user_id uuid FK NULL, status text,  -- 'sent'|'signed_up'|'rewarded'
  reward_granted boolean DEFAULT false, created_at timestamptz DEFAULT now()
)
```

---

## 5. Operational / pipeline tables

### 5.1 `crawl_runs` + `crawl_jobs` (queue + observability)
```sql
crawl_runs (
  id bigserial PK, source_id bigint FK, tier smallint,
  started_at timestamptz, finished_at timestamptz,
  status text,                          -- 'running'|'success'|'partial'|'failed'
  listings_found int, new_opps int, errors int, log jsonb
)
crawl_jobs (                            -- the Postgres-as-queue table (SKIP LOCKED)
  id bigserial PK, source_id bigint FK, scheduled_for timestamptz,
  status text DEFAULT 'pending',        -- 'pending'|'claimed'|'done'|'error'
  attempts int DEFAULT 0, claimed_at timestamptz, locked_by text
)
-- Worker: SELECT ... WHERE status='pending' AND scheduled_for<=now()
--         ORDER BY scheduled_for FOR UPDATE SKIP LOCKED LIMIT k;
```

### 5.2 `source_state` — change detection
```sql
source_state (
  source_id bigint FK, page_key text,   -- which page/board
  last_content_hash text, last_crawled_at timestamptz,
  PK(source_id, page_key)
)
```
> If the hash is unchanged since last crawl, skip re-parsing → saves compute and AI enrichment. Core cost lever (Doc 04/05).

### 5.3 `user_events` — append-only, **partitioned by month**
```sql
user_events (
  id bigserial, user_id uuid, event_type text,   -- 'view'|'click'|'bookmark'|'apply_click'|'share'|'invite_sent'
  opportunity_id bigint NULL, ts timestamptz DEFAULT now(), props jsonb
) PARTITION BY RANGE (ts);
-- monthly partitions: user_events_2026_06, _2026_07, ...
```

---

## 6. Indexing strategy (the read path, deliberately)

| Query | Index |
|-------|-------|
| Keyword search | `GIN (search_tsv)` on `opportunities` |
| Fuzzy company/title | `GIN (name_normalized gin_trgm_ops)`, `GIN (title_normalized gin_trgm_ops)` |
| Feed: active + sort by deadline | `BTREE (status, deadline)` partial `WHERE status='active'` |
| "Closing soon" / heatmap | `BTREE (deadline) WHERE status='active' AND deadline IS NOT NULL` |
| Category/remote filters | `BTREE (category)`, partial indexes per hot filter |
| Semantic / Resume Match | `HNSW (embedding vector_cosine_ops)` on `opportunity_embeddings` |
| Dream-company alert eval | `BTREE (company_id) WHERE status='active'` |
| Dedup lookup | `(source_id, external_id)` unique; trigram on normalized fields |
| Unprocessed raw | partial `WHERE processed=false` |

**Rule:** add an index only when a real query needs it. Each index costs write throughput and storage. Review index usage with `pg_stat_user_indexes`; drop unused ones (Doc 08 review checklist).

---

## 7. Deduplication data design (the hard part)

The dedup *engine logic* lives in Doc 04; here is the *data* that supports it:

1. **Blocking keys** (cheap candidate generation): `(company_id, title_normalized)` and normalized domain. Only compare within a block.
2. **Similarity signals:** trigram similarity on title; embedding cosine on description; deadline + location agreement.
3. **Canonical merge:** when raw listing matches an existing `opportunities` row above threshold → attach via `opportunity_sources`, update `last_seen_at`, keep richest `description_raw`. Below threshold → create new canonical opp.
4. **Evidence preserved:** every contributing `raw_listing` keeps its own row; nothing is destroyed, so a wrong merge is reversible.

---

## 8. Partitioning & growth strategy

- **`user_events`: monthly range partitions** from day one. Highest-volume table; partitioning keeps queries fast and lets old partitions be dropped/archived cheaply.
- **`opportunities`: do NOT partition early.** Postgres handles millions of rows fine with good indexes. Partitioning here is premature complexity. Revisit only past several million active opps.
- **`raw_listings`: archive/prune.** It grows fastest (every crawl). Policy: keep raw payloads 90 days hot, then move to cold object storage (R2/B2) or drop payload but keep hash. Documented retention job.
- **`notifications`: prune** sent rows older than retention window (keep aggregates).
- **Growth ladder:** Supabase free (≤500MB) → Supabase Pro ($25, 8GB+) → read replicas for read path → only then consider sharding. Each step is measurement-triggered (Doc 02 §5).

---

## 9. Backup & DR strategy

- **Managed daily backups** on Supabase Pro (point-in-time recovery on higher tiers).
- **Independent nightly `pg_dump`** (GH Actions cron) → **Cloudflare R2 / Backblaze B2** (cheap, low/no egress). *Never rely solely on the provider.* Keep 7 daily + 4 weekly.
- **Restore drill:** a documented, periodically-tested restore-to-staging procedure. A backup you've never restored is a hope, not a backup.
- **What's precious vs replaceable:** `users`, `subscriptions`, `resume_profiles`, `bookmarks`, `dream_companies`, `referrals`, `user_events` are **irreplaceable** — back up religiously. `raw_listings` and even `opportunities` are **regenerable** by re-crawling — back up, but they're lower DR priority. Optimize backup cost accordingly.

---

## 10. Data integrity & quality

- FKs enforced; `ON DELETE` policies explicit (e.g., deleting a user cascades bookmarks but anonymizes events).
- `last_seen_at` + a sweep job expires stale opps and flags dead links → trust (Doc 01 R5).
- "Report this listing" writes to a `flags` table feeding manual/auto review.
- Deadline parsing confidence (`deadline_confidence`) surfaced in UI so we never display a guessed deadline as fact.

---

## HANDOFF TO ENGINEERING

1. **Migrations are the contract.** Implement the schema above with a real migration tool (Alembic or SQL migrations in Supabase). The canonical opportunity model (§3.4–3.5) and the raw/canonical separation are **non-negotiable**.
2. **Generated `search_tsv`** column (title + company + summary + tags), maintained by trigger or generated column; GIN-index it.
3. **Enable extensions first:** `pg_trgm`, `vector` (pgvector). Pick and freeze the embedding dimension; store `model` so re-embeds are migratable.
4. **`plans.features` jsonb is the only place plan gating lives.** Wire the app's `can(user, feature)` to read it (Doc 02/08).
5. **Partition `user_events` monthly** with an automated "create next month's partition" job. Do not partition `opportunities`.
6. **Postgres-as-queue** for `crawl_jobs` using `FOR UPDATE SKIP LOCKED`; no external queue.
7. **Retention jobs** (GH Actions cron): prune/archive `raw_listings` >90d, expire stale `opportunities` via `last_seen_at`, prune old `notifications`.
8. **Backups:** enable Supabase backups AND an independent nightly `pg_dump` → R2/B2. Document and test one restore before launch.
9. **Two environments:** separate Supabase projects for dev and prod. Never test migrations against prod.

**Definition of done for the data layer:** one canonical opportunity per real-world opportunity, every source linked; fast indexed feed/search/vector queries; events partitioned; gating driven by `plans.features`; backups running and restore-tested.
