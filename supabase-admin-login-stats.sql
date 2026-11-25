-- Run once in Supabase: SQL Editor -> New query -> Run.
-- Lets the Admin page show every user's full login history.
create or replace function public.admin_login_stats()
returns table(user_id uuid, logins bigint, logins30 bigint, active_sessions bigint)
language sql security definer set search_path = auth, public as $$
  select u.id,
    (select count(*) from auth.audit_log_entries a
       where a.payload->>'action' = 'login' and a.payload->>'actor_id' = u.id::text),
    (select count(*) from auth.audit_log_entries a
       where a.payload->>'action' = 'login' and a.payload->>'actor_id' = u.id::text
         and a.created_at >= now() - interval '30 days'),
    (select count(*) from auth.sessions s where s.user_id = u.id)
  from auth.users u;
$$;
revoke all on function public.admin_login_stats() from public, anon, authenticated;
grant execute on function public.admin_login_stats() to service_role;
