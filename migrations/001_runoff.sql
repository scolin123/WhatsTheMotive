-- Runoff round: after results, the host can send the top 3 to a
-- one-vote-each runoff. Run this once in the Supabase SQL editor.

-- null = no runoff, 'voting' = runoff open, 'done' = runoff finished
alter table rooms
  add column if not exists runoff_status text
  check (runoff_status in ('voting', 'done'));

create table if not exists runoff_votes (
  id               uuid primary key default gen_random_uuid(),
  room_id          uuid not null references rooms(id) on delete cascade,
  participant_name text not null,
  suggestion_id    uuid not null references suggestions(id) on delete cascade,
  created_at       timestamptz not null default now(),
  unique (room_id, participant_name)
);

-- The server uses the publishable (anon) key, so RLS needs a policy that
-- lets it read and write, or every runoff vote is rejected.
alter table runoff_votes enable row level security;

drop policy if exists "anon all" on runoff_votes;
create policy "anon all" on runoff_votes
  for all using (true) with check (true);

-- Make the API see the new column/table right away
notify pgrst, 'reload schema';
