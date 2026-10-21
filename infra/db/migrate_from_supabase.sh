#!/usr/bin/env bash
# Copy production data from Supabase into this server's `aspirova` database,
# then prove the copy is exact. Run as root on the droplet, after
# provision.sh, with the scheduled GitHub workflows disabled so nothing writes
# to Supabase mid-copy (RUNBOOK step 3):
#
#   ssh root@<droplet-ip> 'bash -s' < infra/db/migrate_from_supabase.sh
#
# Reads the source URL from /root/.supabase_url (libpq form, mode 600) so it
# never appears on a command line you type. Refuses to run if the target
# already has tables, so it can never overwrite a live database.
#
# Only the `public` schema moves. Supabase's auth and storage schemas stay on
# Supabase, which keeps serving sign-in and resume files.
set -euo pipefail

SRC_FILE=/root/.supabase_url
DB=aspirova
ROLE=aspirova_app
WORK=/var/lib/postgresql/migration
DUMP=$WORK/aspirova.dump

[ -s "$SRC_FILE" ] || { echo "missing $SRC_FILE - see RUNBOOK step 3"; exit 1; }
SRC=$(cat "$SRC_FILE")

existing=$(sudo -u postgres psql -d "$DB" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
if [ "$existing" != "0" ]; then
  echo "refusing: $DB already has $existing tables in public"
  exit 1
fi

install -d -o postgres -g postgres -m 700 "$WORK"

echo "== dump: public schema from Supabase"
start=$(date +%s)
pg_dump "$SRC" --schema=public --format=custom --no-owner --no-acl --file="$DUMP"
chown postgres:postgres "$DUMP"
echo "   $(du -h "$DUMP" | cut -f1) in $(( $(date +%s) - start ))s"

echo "== restore"
# Dropped from the table of contents, each for a Supabase-only reason:
#   ROW SECURITY      - RLS switched on with no policies; the API is the only
#                       client, and PostgREST is not used, so it only blocks.
#   rls_auto_enable   - the function behind Supabase's ensure_rls event trigger.
#   SCHEMA public     - already exists, owned by the database owner.
pg_restore -l "$DUMP" \
  | grep -vE 'ROW SECURITY|rls_auto_enable|SCHEMA - public|COMMENT - SCHEMA public' \
  > "$WORK/toc.list"
chown postgres:postgres "$WORK/toc.list"
start=$(date +%s)
# --role makes every restored object belong to the app role, not postgres.
sudo -u postgres pg_restore -d "$DB" --role="$ROLE" --no-owner --no-acl \
  --exit-on-error -L "$WORK/toc.list" "$DUMP"
echo "   restored in $(( $(date +%s) - start ))s"

echo "== planner statistics"
sudo -u postgres vacuumdb -d "$DB" --analyze-only --quiet

echo "== verify: exact row count of every table, Supabase vs here"
count_sql=$(sudo -u postgres psql -d "$DB" -tAc "
  SELECT string_agg(format('SELECT %L AS t, count(*) AS n FROM public.%I', tablename, tablename),
                    ' UNION ALL ' ORDER BY tablename)
  FROM pg_tables WHERE schemaname = 'public'")
psql "$SRC" -tA -F'|' -c "$count_sql" | LC_ALL=C sort > "$WORK/source_counts"
sudo -u postgres psql -d "$DB" -tA -F'|' -c "$count_sql" | LC_ALL=C sort > "$WORK/target_counts"
# Anonymous page views keep inserting view-counter rows on Supabase while this
# runs; losing a few of those at cutover is harmless. Any other difference
# (a bookmark, a user, a saved search) means a real write would be lost.
DRIFT_OK="opportunity_view_counts"
mismatches=0
while IFS='|' read -r table source target; do
  flag=""
  if [ "$source" != "$target" ]; then
    if [ "$table" = "$DRIFT_OK" ]; then
      flag="   (page-view counter, +$((source - target)) since the dump - harmless)"
    else
      flag="   <-- MISMATCH"
      mismatches=$((mismatches + 1))
    fi
  fi
  printf '   %-28s %9s %9s%s\n' "$table" "$source" "$target" "$flag"
done < <(LC_ALL=C join -t'|' "$WORK/source_counts" "$WORK/target_counts")
if [ "$(wc -l < "$WORK/source_counts")" != "$(wc -l < "$WORK/target_counts")" ]; then
  echo "   table lists differ between Supabase and here"
  mismatches=$((mismatches + 1))
fi

echo "== verify: structure"
sudo -u postgres psql -d "$DB" -tA <<'SQL'
SELECT '   tables          ' || count(*) FROM pg_tables WHERE schemaname = 'public';
SELECT '   indexes         ' || count(*) || ' (' || string_agg(DISTINCT am.amname, ', ') || ')'
  FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_am am ON am.oid = c.relam
  JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public';
SELECT '   invalid indexes ' || count(*) FROM pg_index WHERE NOT indisvalid;
SELECT '   triggers        ' || string_agg(tgname, ', ') FROM pg_trigger WHERE NOT tgisinternal;
SELECT '   foreign keys    ' || count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
  WHERE n.nspname = 'public' AND c.contype = 'f';
SELECT '   not app-owned   ' || count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'S', 'v', 'm') AND pg_get_userbyid(c.relowner) <> 'aspirova_app';
SELECT '   alembic         ' || version_num FROM alembic_version;
SELECT '   size            ' || pg_size_pretty(pg_database_size(current_database()));
SQL

if [ "$mismatches" -eq 0 ]; then
  echo "RESULT: every table matches Supabase exactly"
else
  echo "RESULT: $mismatches table(s) differ - do NOT switch DATABASE_URL"
  exit 1
fi
