-- Run once in Supabase SQL editor
create table if not exists public.user_prefs (
  user_id        uuid primary key references auth.users(id) on delete cascade,
  digest_freq    text not null default 'weekly'  check (digest_freq in ('off','daily','weekly')),
  statement_freq text not null default 'monthly' check (statement_freq in ('off','weekly','monthly','quarterly','half_yearly','annual')),
  fund_prefs     jsonb,
  last_digest_at    timestamptz,
  last_statement_at timestamptz,
  updated_at     timestamptz not null default now()
);
alter table public.user_prefs enable row level security;
create policy "own prefs select" on public.user_prefs for select using (auth.uid() = user_id);
create policy "own prefs insert" on public.user_prefs for insert with check (auth.uid() = user_id);
create policy "own prefs update" on public.user_prefs for update using (auth.uid() = user_id);

-- Table privileges (newer Supabase projects do not grant these automatically)
grant select, insert, update, delete on public.user_prefs to authenticated;
grant all on public.user_prefs to service_role;
