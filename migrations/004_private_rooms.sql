-- Private rooms: the host approves each person before they join.
-- Run this once in the Supabase SQL editor BEFORE deploying the matching code.

-- false = public (anyone with the code joins instantly), true = private
alter table rooms
  add column if not exists is_private boolean not null default false;

-- One row per person asking to join a private room.
create table if not exists join_requests (
  id           uuid primary key default gen_random_uuid(),
  room_id      uuid not null references rooms(id) on delete cascade,
  display_name text not null,
  status       text not null default 'pending'
               check (status in ('pending', 'approved', 'denied')),
  created_at   timestamptz not null default now(),
  unique (room_id, display_name)
);

alter table join_requests enable row level security;

drop policy if exists "anon all" on join_requests;
create policy "anon all" on join_requests
  for all using (true) with check (true);

notify pgrst, 'reload schema';
