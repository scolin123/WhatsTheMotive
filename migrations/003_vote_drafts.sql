-- Vote drafts: the order each person currently has on screen while voting.
-- When voting closes, drafts of people who never pressed Submit become real
-- ballots. Run this once in the Supabase SQL editor.

create table if not exists vote_drafts (
  id               uuid primary key default gen_random_uuid(),
  room_id          uuid not null references rooms(id) on delete cascade,
  participant_name text not null,
  ranked_ids       jsonb not null,
  updated_at       timestamptz not null default now(),
  unique (room_id, participant_name)
);

alter table vote_drafts enable row level security;

drop policy if exists "anon all" on vote_drafts;
create policy "anon all" on vote_drafts
  for all using (true) with check (true);

notify pgrst, 'reload schema';
