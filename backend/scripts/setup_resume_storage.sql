-- One-time Supabase Storage setup for the persistent-resume feature.
-- ALREADY APPLIED TO PROD 2026-07-26 (bucket + 4 policies created as role `postgres`).
-- Kept here for reproducibility if the project is ever rebuilt. Run with an
-- elevated role (Supabase SQL editor = postgres, or the direct postgres
-- connection). RLS on storage.objects is already enabled by Supabase.
--
-- Model: one resume per user at path  resumes/{user_id}/resume.pdf
-- Private bucket + owner-only policies (a user can only touch objects whose
-- first path segment equals their auth uid). The app uploads/reads directly
-- from the browser with the user's JWT; these policies are what authorize it.

-- 1) Private bucket, PDF-only, 5 MB cap.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('resumes', 'resumes', false, 5242880, array['application/pdf'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- 2) Owner-only policies.
drop policy if exists "resumes owner read"   on storage.objects;
drop policy if exists "resumes owner insert" on storage.objects;
drop policy if exists "resumes owner update" on storage.objects;
drop policy if exists "resumes owner delete" on storage.objects;

create policy "resumes owner read" on storage.objects for select to authenticated
  using (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "resumes owner insert" on storage.objects for insert to authenticated
  with check (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "resumes owner update" on storage.objects for update to authenticated
  using (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "resumes owner delete" on storage.objects for delete to authenticated
  using (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);
