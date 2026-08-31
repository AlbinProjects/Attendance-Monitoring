-- =============================================================================
-- Migration 003: Row Level Security policies
--
-- Postgres RLS is deny-by-default: enabling RLS on a table with zero
-- matching policies means NO ONE (except a service-role/superuser
-- connection, which bypasses RLS entirely) can read or write it. Every
-- policy below is deliberately narrow. Where the spec says a capability
-- doesn't exist (e.g. "employees cannot delete audit logs"), we simply do
-- not write a policy for it rather than writing one and hoping it's never
-- called — omission is the enforcement.
--
-- Reminder: the FastAPI backend's primary write path uses the Supabase
-- service-role key, which bypasses RLS. These policies are the second layer
-- of defense described in README "Security principles" — they protect
-- against a compromised anon key, a frontend bug that queries Supabase
-- directly, or a bypass attempt that skips the backend entirely.
-- =============================================================================

alter table employees enable row level security;
alter table attendance enable row level security;
alter table performance_updates enable row level security;
alter table activity_sessions enable row level security;
alter table audit_logs enable row level security;
alter table company_settings enable row level security;

-- -----------------------------------------------------------------------------
-- employees
-- -----------------------------------------------------------------------------

-- Everyone can see their own profile; admins/super admins can see everyone.
create policy employees_select on employees
    for select
    using (
        auth_user_id = auth.uid()
        or is_admin_or_above()
    );

-- Only Super Admin can create employee rows directly against Postgres.
-- In practice employee creation goes through the backend (which first
-- creates the Supabase Auth user via the admin API, then inserts this row
-- using the service-role key), but this policy still applies if a Super
-- Admin's own authenticated session is ever used for a direct insert.
create policy employees_insert_super_admin on employees
    for insert
    with check (is_super_admin());

-- Only Super Admin can update employee rows (role changes, disabling,
-- department/designation edits). A regular employee has NO update policy —
-- they cannot change their own role, employee_code, or is_active flag.
create policy employees_update_super_admin on employees
    for update
    using (is_super_admin())
    with check (is_super_admin());

-- No delete policy for anyone. Employees are disabled via is_active, never
-- deleted, so history is preserved (see README).

-- -----------------------------------------------------------------------------
-- attendance
-- -----------------------------------------------------------------------------

-- Employees see only their own attendance; admins/super admins see all.
create policy attendance_select on attendance
    for select
    using (
        employee_id = auth_employee_id()
        or is_admin_or_above()
    );

-- Regular employees never insert attendance directly — check-in/out is
-- always mediated by the backend (server time, IP verification, duplicate
-- checks). This policy only allows admin/super_admin, and only when they've
-- supplied a marked_by + reason (enforced by the table's own CHECK
-- constraint plus this policy).
create policy attendance_insert_admin on attendance
    for insert
    with check (
        is_admin_or_above()
        and marked_by = auth_employee_id()
    );

-- Same reasoning for updates: only admins, and only with a reason recorded.
create policy attendance_update_admin on attendance
    for update
    using (is_admin_or_above())
    with check (
        is_admin_or_above()
        and reason is not null
    );

-- No delete policy for anyone — attendance history is never removed, only
-- corrected with a new audited admin update (see README "Never silently
-- overwrite history").

-- -----------------------------------------------------------------------------
-- performance_updates
-- -----------------------------------------------------------------------------

create policy performance_select on performance_updates
    for select
    using (
        employee_id = auth_employee_id()
        or is_admin_or_above()
    );

-- Employees may insert only their OWN report, and only for today or
-- yesterday's work_date (the "older dates require admin" rule). Full 5 PM
-- availability logic still lives in the backend (Phase 5) — this is a
-- coarse database-level backstop, not the primary enforcement.
create policy performance_insert_own_recent on performance_updates
    for insert
    with check (
        employee_id = auth_employee_id()
        and work_date >= (current_date - interval '1 day')
        and work_date <= current_date
    );

-- Admins/super admins can insert on behalf of any employee for any date
-- (authorized backdating/correction per README section 29).
create policy performance_insert_admin on performance_updates
    for insert
    with check (is_admin_or_above());

-- Employees may update only their own recent (today/yesterday) report,
-- e.g. correcting a typo before it's reviewed. Admins may update anything.
create policy performance_update_own_recent on performance_updates
    for update
    using (
        employee_id = auth_employee_id()
        and work_date >= (current_date - interval '1 day')
    )
    with check (
        employee_id = auth_employee_id()
        and work_date >= (current_date - interval '1 day')
    );

create policy performance_update_admin on performance_updates
    for update
    using (is_admin_or_above())
    with check (is_admin_or_above());

-- No delete policy — performance history is never removed.

-- -----------------------------------------------------------------------------
-- activity_sessions
-- -----------------------------------------------------------------------------

create policy activity_select on activity_sessions
    for select
    using (
        employee_id = auth_employee_id()
        or is_admin_or_above()
    );

-- Heartbeats: an employee may only write rows tied to their own attendance
-- session. The backend still validates that attendance_id actually
-- corresponds to an open session before accepting a heartbeat (Phase 6).
create policy activity_insert_own on activity_sessions
    for insert
    with check (employee_id = auth_employee_id());

create policy activity_update_own on activity_sessions
    for update
    using (employee_id = auth_employee_id())
    with check (employee_id = auth_employee_id());

-- No delete policy — inactivity periods are never removed once recorded.

-- -----------------------------------------------------------------------------
-- audit_logs
-- -----------------------------------------------------------------------------

-- Only admins/super admins can read audit logs. No INSERT/UPDATE/DELETE
-- policy exists for ANY authenticated role — audit rows are written
-- exclusively by the backend's service-role connection (which bypasses RLS),
-- guaranteeing they cannot be tampered with or fabricated by a client, admin
-- or otherwise, through the public API surface.
create policy audit_logs_select_admin on audit_logs
    for select
    using (is_admin_or_above());

-- -----------------------------------------------------------------------------
-- company_settings
-- -----------------------------------------------------------------------------

-- Any authenticated, active employee can read settings (e.g. the frontend
-- needs performance_start_time to render the "available at 5 PM" state).
create policy company_settings_select_authenticated on company_settings
    for select
    using (auth_is_active());

-- Only Super Admin can change settings.
create policy company_settings_update_super_admin on company_settings
    for update
    using (is_super_admin())
    with check (is_super_admin());

-- No insert/delete policy — the single settings row is created once by
-- migration 004 and never removed.
