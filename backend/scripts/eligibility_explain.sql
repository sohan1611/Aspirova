-- Run with psql ONLY against a disposable local Postgres database.
-- Synthetic data only. No application tables or private samples are read.
-- Compare the Execution Time lines; repeat with a warm cache and record medians.
BEGIN;
CREATE TEMP TABLE eligibility_benchmark AS
SELECT id,
       repeat('Synthetic listing prose. ', 200) AS description_raw,
       CASE id % 4
           WHEN 0 THEN NULL::jsonb
           WHEN 1 THEN '{"v":1}'::jsonb
           WHEN 2 THEN '{"v":1,"grad_years":{"value":[2026]},"stages":{"value":["undergraduate"]}}'::jsonb
           ELSE '{"v":1,"grad_years":{"value":[2025]},"stages":{"value":["postgraduate"]}}'::jsonb
       END AS eligibility_facts
FROM generate_series(1, 27000) AS id;
ANALYZE eligibility_benchmark;

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM eligibility_benchmark;

-- Unknown-preserving graduation-year predicate.
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM eligibility_benchmark
WHERE (jsonb_typeof(eligibility_facts['grad_years']['value']) = 'array') IS NOT TRUE
   OR (eligibility_facts['grad_years']['value'] @> '[2026]'::jsonb) IS TRUE;

-- Both dimensions; missing information is retained independently.
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM eligibility_benchmark
WHERE ((jsonb_typeof(eligibility_facts['grad_years']['value']) = 'array') IS NOT TRUE
        OR (eligibility_facts['grad_years']['value'] @> '[2026]'::jsonb) IS TRUE)
  AND ((jsonb_typeof(eligibility_facts['stages']['value']) = 'array') IS NOT TRUE
        OR (eligibility_facts['stages']['value'] @> '["undergraduate"]'::jsonb) IS TRUE);

-- Explicit evidence-only opt-in.
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM eligibility_benchmark
WHERE (jsonb_typeof(eligibility_facts['grad_years']['value']) = 'array') IS TRUE
  AND (eligibility_facts['grad_years']['value'] @> '[2026]'::jsonb) IS TRUE
  AND (jsonb_typeof(eligibility_facts['stages']['value']) = 'array') IS TRUE
  AND (eligibility_facts['stages']['value'] @> '["undergraduate"]'::jsonb) IS TRUE;
ROLLBACK;
