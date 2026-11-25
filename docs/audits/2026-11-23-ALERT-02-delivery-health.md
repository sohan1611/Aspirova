# ALERT-02 — email delivery health and recovery

## Investigation: before this change

Every application-owned Resend request ultimately called `core/email_client.py`.
It discarded the provider message ID, returned only a boolean, caught every
provider exception, and logged recipient addresses plus exception tracebacks.
Timeouts, connection errors, 429, 5xx and permanent 4xx were indistinguishable.
There was no durable intended-email record, attempt history, lease, backoff,
provider idempotency header, Resend delivery webhook, or address suppression list.

| Sender | Existing record and failure behavior |
| --- | --- |
| `pipeline/notifications.py`: daily digest, including hackathons and programme watches | One sent/failed `Notification` per digest. Successful rows advanced digest history and watch cursors. Failed rows did not consume the daily cap, so another selector run could try again, but there was no persisted original payload or retry schedule. |
| Same file: company alerts and instant alerts | One email for a group, with one sent/failed ledger row per selected opportunity. Both use type `instant_alert`. Failed groups could be selected again; acceptance followed by a lost response or failed ledger commit could duplicate mail. |
| Same file: closing-soon, saved-listing safety and early-closure notices | Per-opportunity delivery rows; in-app notices retain `email_pending` until successful email. Notice-only successes had an additional budget ledger row. Failed sends had no durable email payload and could be recomposed later. |
| `pipeline/saved_search_alerts.py` | One sent/failed row per search email. **`last_alerted_at` advanced even after failure**, so future selection could silently lose the failed matches. |
| `pipeline/weekly_report.py` | One sent/failed row, capped by ISO week on success. Failure could be selected later, with newly rendered contents, without backoff or a durable retry. |
| `api/payments.py`: subscription activation/payment failure | Billing state committed first, then best-effort mail and a sent/failed notification. Webhook replays without another status transition did not retry failed mail. |
| Same file: founder billing reconciliation | Best-effort send, without a delivery ledger or recovery. |
| `api/account.py`: account deletion confirmation | Best-effort send after the tombstone committed; failures were logged, without durable recovery. |
| `api/reports.py`: founder report intake | Report persisted first, then best-effort mail. No delivery ledger or recovery. |
| `api/waitlist.py`: founder waitlist notification | Best-effort send and always an OK marketing response, without persistence or recovery. |
| `scripts/reports.py`: resolution email and overdue-report reminder | Best-effort sends, without delivery history or retry state. |
| Supabase Auth confirmation/password-reset SMTP | Externally managed Auth mail, outside the application's HTTP sender and ledger. Its existing SMTP configuration is unchanged; no production credentials or Auth configuration were accessed. |

`core/alert_identity.py` (ALERT-03) reads successful email ledger rows, using
immutable role/version snapshots, with legacy opportunity/batch fallbacks. New
listing events share cross-source identities; closing-soon identities version by
UTC deadline date. In-app rows do not suppress email. This identity policy and
all rendered mail contents are preserved.

Before this change, the budget snapshot counted **successful email notification
rows**, not requests. Grouped sends could count several times; failed requests
counted zero. Workers allowed 85 per UTC day; digests stopped at 75 to leave 10
for other kinds. The remaining 15 of Resend Free's 100/day were headroom for
API mail and external Auth SMTP. Concurrent snapshots could overshoot.

Workers printed result counts but normally exited successfully after provider
rejects. Company alerts also used `continue-on-error`. A green workflow therefore
did not prove delivery. Local history confirms #129 fixed test dates, #130 sign-in
behavior, and #131 Razorpay webhook ordering (`0872f07`/`70e8c9c`); these did not
provide Resend delivery webhooks or suppression.

## Design and behavior

- `email_outbox`: one unique hashed intent key, user/recipient/kind, immutable
  provider payload, receipt references, cursor effects, status, attempt count,
  due time, lease/token, uncertainty timestamp, safe vendor error, message ID and
  lifecycle timestamps. The payload is private database data, never API output.
- `email_attempts`: a separate row per attempt, with a composite primary key.
  This allows indexed daily accounting and append-only attempt history without
  rewriting an increasingly large JSON array. An abandoned lease remains visible.
- `email_budget_days`: a PII-free daily high-water counter. It prevents deletion
  of account-owned payloads/attempts from freeing already consumed quota.
- `email_suppressions`: normalized address, cause and time.
- `email_webhook_events`: verified event ID, message ID, type and time only;
  raw event bodies and recipient lists are not retained.
- `notifications.outbox_id` associates the existing ledger receipts with an
  intent. Retries update these same rows; they never append another sent receipt.
  Watch/notice flags and search cursors commit atomically with first acceptance. Search cursors use the original selection cutoff, so outage-window matches are not skipped and later webhooks cannot advance the cursor again.

An intent commits before claiming. A claim, lease, attempt and budget reservation
commit **before** HTTP. The provider receives the stored payload and the same
`Idempotency-Key` on every retry. The default lease is 300 seconds; HTTP timeout
is 20 seconds. Overlapping workers use row locks, sender-only address locks and
a global budget lock. Ordinary authenticated browsing keeps its key-share lock.
Pending identities/notices are reserved so another sender cannot recompose them. Queued attempts recheck opt-outs, removed saved searches, programme watches/official evidence, and cleared saved-listing warnings before retry; cancelled payloads are suppressed rather than edited under an existing key.

5xx, network errors, timeouts, 408, 429 and a concurrent-idempotent-request 409
retry with exponential backoff and jitter; numeric and HTTP-date `Retry-After`
are respected. Other 4xx fail permanently. Six attempts dead-letter by default.
Due queued rows and expired leases are recovered automatically on the next
worker run. No process sleeps while holding a lease for backoff.

All application HTTP attempts, including API mail and retries, now share the
85/day cap; digests still leave 10 slots. This conservatively brings formerly
unmetered API sends under the existing cap and preserves 15 slots for external
Auth SMTP. Exhausted rows remain queued until UTC midnight. Actual attempt time,
not the batch's selection time, controls leases and daily accounting.

Resend retains idempotency keys for **24 hours**. An uncertain request is never
submitted after 23 hours from its first uncertain attempt. It becomes dead and
requires provider reconciliation. Recovery cannot force a stale uncertain key:
doing so could duplicate an accepted message. Known provider IDs always prevent
another submission. Reference: [Resend idempotency keys](https://resend.com/docs/dashboard/emails/idempotency-keys).

`POST /email/webhook` verifies raw bytes with the installed Resend SDK's Svix
HMAC/timestamp verification, then deduplicates event IDs transactionally. Tags
correlate lost HTTP responses to intents. Delivered, bounced, complained, failed
and suppressed events are recorded monotonically. Hard bounces and complaints
suppress pending and future mail. Accepted-but-undeliverable intents become
failed for operator visibility, retaining their accepted ledger identity; they
are never resent. Older delivered events cannot undo a complaint or bounce.
Reference: [Resend webhook verification](https://resend.com/docs/webhooks/verify-webhooks-requests).

Provider error text can echo personal payloads or credentials. Persisted/public
error messages use safe provider categories and fixed descriptions; unknown
details are redacted. Worker logs contain counts. SQLAlchemy hides bound
parameters so a database exception cannot dump a full email body.

No dependencies were added. Existing `httpx` supplies HTTP status/Retry-After
that the old boolean SDK seam discarded. The installed Resend SDK verifies hooks.

## Operator use and rollout

The founder runs migration `ab6c9d2e4f71` before merge/deploy. It uses the existing
3-second lock timeout and five bounded savepoint retries. There is no payload
backfill: old sent ledger rows remain authoritative and conservatively count on
deployment day; old failures have no safely reconstructable payload or key.

Configure `DELIVERY_ADMIN_TOKEN` and `RESEND_WEBHOOK_SECRET` on the API server.
Register `/email/webhook` for `email.sent`, `email.delivered`, `email.bounced`,
`email.complained`, `email.failed`, and `email.suppressed` in Resend. These are
founder rollout steps; this work did not access production or a real API key.

There was no admin UI or founder role. `/admin/delivery/view` is a plain API-hosted
page; enter the admin token there. The protected `/admin/delivery` API shows seven
days of counts by kind/status, safe latest errors, delivery outcomes, suppression
count and today's quota use. Token input stays in memory; no URL/storage/client
environment variable carries it. Responses are `no-store`; no recipient data or
email bodies are returned. No frontend build change is needed.

From `backend/`, with the founder's normal server-side environment:

```sh
python -m scripts.delivery_health counts
python -m scripts.delivery_health requeue          # dry run first
python -m scripts.delivery_health requeue --apply  # safe transient dead rows only
python -m scripts.delivery_health drain
```

Recovery retains keys, payloads, monotonic attempt history and the quota counter.
Permanent failures and expired uncertain attempts are not automatically requeued.
Notification workers drain due mail before selection, print status counts and
exit nonzero while dead/failed intents remain. Company errors are no longer
ignored by the workflow, and independent steps still run after another fails.

## Validation

The fake HTTP transport injects 503, timeout, connection reset, 429/Retry-After,
acceptance with a lost response, permanent 422, a crash after acceptance, and a
failed local acceptance commit. Tests cover lease recovery, concurrent workers,
global quota races, next-day deferral, quota survival after payload deletion,
dry-run recovery, key-window expiry, signed hook replay, asynchronous failure,
hard-bounce/complaint suppression, out-of-order events and tagged reconciliation.
They assert immutable retry payloads/keys and no duplicate sent receipts.

The exact new migration upgrades/downgrades in isolated local PostgreSQL schemas.
The 27 delivery tests pass. Full migration-chain validation is blocked because
the installed PostgreSQL 17 lacks `vector`; Docker engine access is denied.
The normal full pytest command stops on missing baseline tables after that
migration rollback. This is not a green full backend suite.

Local outage drill (isolated schema on a dedicated localhost test database):

```sh
python -m scripts.delivery_outage_drill --database-url \
  postgresql+psycopg://postgres:postgres@127.0.0.1:5432/aspirova_delivery_test
```

```text
{"phase": "outage", "queued": 20}
{"phase": "recovered", "sent": 20}
{"accepted": 20, "attempts": 40, "duplicate_sent_events": 0, "sent_events": 20}
```

The drill pins loopback, rejects URL connection overrides/non-test database names,
creates a generated throwaway schema, mocks all Resend HTTP with a fake-only key,
does not load `.env`, and drops its schema afterwards.

Validation completed with these results (all passing commands exited 0):

- **264 backend tests passed**, including 27 real-Postgres delivery scenarios,
  ALERT-03/ALERT-01 unit tests, budget tests, email rendering, subscription-status
  handoff tests, and waitlist tests. The delivery scenarios use the exact new
  migration in isolated schemas; they do not need vector substitutions.
- **467 existing mail integration tests passed** in a separate localhost
  compatibility database: notification selectors, identities, programme watches,
  safety notices, saved searches, weekly mail, budgets, payment webhooks, deletion,
  per-user isolation, digest reliability/hackathons, billing reconciliation, report
  triage and digest APIs. Only this compatibility run substitutes TEXT for unused
  vector columns/casts and omits vector extension/HNSW creation. It verifies the
  changed mail paths but does **not** establish a full pgvector-suite pass. Both
  dedicated test databases contained only synthetic local data.
- **327 frontend node tests passed**; ESLint and `tsc --noEmit` exited 0.
- Backend **ruff**, **black --check**, and **git diff --check** exited 0.
- The outage drill exited 0 with the exact output above.

Legacy tests were updated to recover the original intent after backoff, update
one receipt instead of appending failed/sent duplicates, preserve failed search
cursors, and expect durable budget deferrals. Retry bodies now stay frozen even
when programme data changes meanwhile; new programme changes retain their own
pending notice for a subsequent digest. A UTC range replaces a database-local
DATE comparison for the company/digest daily cap. No live provider test, full
pgvector suite, production migration, deployment or commit/push was performed.

## Draft PR description

**Title:** Persist email delivery attempts and recover safely from provider outages

Workers could finish green after rejected mail, and lost acceptance responses
could cause duplicate sends. Route application mail through a Postgres outbox
with stable Resend idempotency keys, leases, retry/backoff, quota reservations,
signed delivery webhooks and suppression. Keep existing content and alert
identities; commit their receipts/cursors only with acceptance.

Add founder delivery counts/errors and dry-run dead-letter recovery. Stale
uncertain sends stop before Resend's 24-hour key expiry. Apply the migration and
configure webhook/admin secrets before deployment. Fake-provider outage tests
and the local drill verify recovery without duplicate sent events; the full
backend pgvector suite still requires verification in a pgvector environment.


## File manifest

- `.github/workflows/notifications-digest.yml` ? Surface company failures and continue independent steps.
- `backend/.env.example` ? Document blank webhook/admin secrets and existing/default delivery limits.
- `backend/api/account.py` ? Persist deletion confirmations after the tombstone commit.
- `backend/api/main.py` ? Register delivery webhook and founder health routes.
- `backend/api/payments.py` ? Queue subscription mail with ledger snapshots and billing reconciliation intents.
- `backend/api/reports.py` ? Queue founder report intake with a stable report identity.
- `backend/api/waitlist.py` ? Queue founder waitlist notifications with a stable signup identity.
- `backend/core/account_deletion.py` ? Purge user-owned email payloads and their dependent records.
- `backend/core/alert_identity.py` ? Reserve pending role/version identities while retaining legacy sent dedupe.
- `backend/core/config.py` ? Add delivery lease, attempt, webhook and founder-token settings.
- `backend/core/db.py` ? Hide bound parameters in database exception logs.
- `backend/core/email_budget.py` ? Count attempts and retained quota reservations with UTC boundaries.
- `backend/core/email_client.py` ? Route every application HTTP send through the outbox and stable provider header.
- `backend/core/mail_recipients.py` ? Serialize email selection across sender kinds without serializing browsing.
- `backend/core/models.py` ? Mirror outbox, attempts, quota, suppression, webhook and ledger-link schema.
- `backend/pipeline/notifications.py` ? Queue digest, company and saved-listing mail with immutable receipt/effect snapshots.
- `backend/pipeline/programme_watch_notifications.py` ? Keep already queued watch notices out of new compositions.
- `backend/pipeline/saved_search_alerts.py` ? Persist search matches and advance only their accepted original cutoff.
- `backend/pipeline/weekly_report.py` ? Queue weekly reports under stable ISO-week identities.
- `backend/scripts/notification_worker.py` ? Drain due/expired intents and surface terminal delivery counts.
- `backend/scripts/reports.py` ? Queue resolution and overdue-report messages with domain event identities.
- `backend/tests/test_account_deletion.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_alert_identity.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_alert_identity_unit.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_email_budget.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_email_client.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_email_components.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_notification_isolation.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_notifications.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_payments_subscription_emails.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_programme_watch_digest.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_saved_listing_notifications.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_saved_search_alerts.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_switch_to_annual.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `backend/tests/test_waitlist.py` ? Update email regression fixtures/assertions for durable intents, recovery and receipt identity.
- `docs/README.md` ? Append the requested Binding delivery decision.
- `backend/api/delivery.py` ? Verify Resend signatures and serve the protected health API/plain page.
- `backend/core/email_events.py` ? Apply replay-safe delivery outcomes and address suppression.
- `backend/core/email_outbox.py` ? Persist intents, leases, attempts, quota, retry/backoff, receipts and safe recovery.
- `backend/migrations/versions/ab6c9d2e4f71_email_delivery_outbox.py` ? Create delivery tables and ledger FK using bounded lock retries.
- `backend/scripts/delivery_health.py` ? Provide counts, dry-run-first requeue and queue draining.
- `backend/scripts/delivery_outage_drill.py` ? Exercise a fake-only outage in a guarded disposable local schema.
- `backend/tests/test_delivery_health.py` ? Prove provider failure, crash, quota, webhook, suppression and cursor recovery invariants.
- `docs/audits/2026-11-23-ALERT-02-delivery-health.md` ? Record investigation, design, rollout, validation, file manifest and draft PR text.
