-- =============================================================================
-- Migration 005: activity_heartbeats
--
-- One row per currently-open attendance session, holding only the
-- timestamp of the most recent detected browser activity. This is
-- intentionally the ONLY per-session mutable state kept for activity
-- monitoring — actual inactivity periods are derived and written to the
-- existing `activity_sessions` table (summarized periods, not raw events)
-- by the backend when a new heartbeat arrives after a gap. See
-- backend/app/services/activity_service.py.
-- =============================================================================

create table activity_heartbeats (
    attendance_id       uuid primary key references attendance(id) on delete cascade,
    employee_id         uuid not null references employees(id) on delete restrict,
    last_heartbeat_at   timestamptz not null,
    updated_at          timestamptz not null default now()
);

create index idx_activity_heartbeats_employee on activity_heartbeats(employee_id);

create trigger trg_activity_heartbeats_updated_at
    before update on activity_heartbeats
    for each row execute function set_updated_at();

alter table activity_heartbeats enable row level security;

-- Employees see only their own current heartbeat row; admins see all
-- (useful for a "who's currently active" live admin view later).
create policy activity_heartbeats_select on activity_heartbeats
    for select
    using (
        employee_id = auth_employee_id()
        or is_admin_or_above()
    );

-- An employee may only write heartbeats tied to their own employee_id. The
-- backend additionally validates that attendance_id corresponds to their
-- own OPEN (checked-in, not checked-out) session before ever calling this
-- (see activity_service.record_heartbeat) — this policy is the second
-- layer of defense, not the only one.
create policy activity_heartbeats_insert_own on activity_heartbeats
    for insert
    with check (employee_id = auth_employee_id());

create policy activity_heartbeats_update_own on activity_heartbeats
    for update
    using (employee_id = auth_employee_id())
    with check (employee_id = auth_employee_id());

-- No delete policy — heartbeat rows are harmless to leave in place after a
-- session ends (they're just a "last seen" pointer, not a growing log) and
-- deleting them isn't required for correctness.
