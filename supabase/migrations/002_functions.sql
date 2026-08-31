-- =============================================================================
-- Migration 002: RLS helper functions
--
-- These are SECURITY DEFINER and STABLE: they run with the privileges of the
-- function owner (bypassing RLS internally) so that a policy on `employees`
-- can safely call auth_role() without recursively re-evaluating the
-- `employees` RLS policy against itself (which would either infinite-loop or
-- silently return no rows). Each function only ever reads a single row keyed
-- off auth.uid(), so this does not create a privilege-escalation path.
-- =============================================================================

-- The employees.id of the currently authenticated user, or NULL if the
-- caller is unauthenticated or has no matching employee row.
create or replace function auth_employee_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
    select id from employees where auth_user_id = auth.uid();
$$;

-- The role ('employee' | 'admin' | 'super_admin') of the currently
-- authenticated user, or NULL if not found.
create or replace function auth_role()
returns text
language sql
stable
security definer
set search_path = public
as $$
    select role from employees where auth_user_id = auth.uid();
$$;

-- True if the current user is an active employee of any role. Inactive
-- (disabled) accounts are treated as unauthenticated for RLS purposes even
-- though their Supabase Auth login may still technically succeed — the
-- backend additionally rejects inactive accounts at the API layer (Phase 3).
create or replace function auth_is_active()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select coalesce(is_active, false) from employees where auth_user_id = auth.uid();
$$;

create or replace function is_admin_or_above()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select auth_is_active() and auth_role() in ('admin', 'super_admin');
$$;

create or replace function is_super_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select auth_is_active() and auth_role() = 'super_admin';
$$;
