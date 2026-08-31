-- =============================================================================
-- Migration 001: Core schema
-- Run this in the Supabase SQL editor (or via `supabase db push`) after
-- creating the project and enabling Authentication (email/password).
-- =============================================================================

create extension if not exists "pgcrypto"; -- for gen_random_uuid()

-- -----------------------------------------------------------------------------
-- employees
-- One row per person who can log in. Linked 1:1 to a Supabase Auth user.
-- Role lives here, NOT in auth.users metadata, so it can only be changed via
-- a Super Admin backend action that also writes an audit log.
-- -----------------------------------------------------------------------------
create table employees (
    id              uuid primary key default gen_random_uuid(),
    auth_user_id    uuid not null unique references auth.users(id) on delete restrict,
    employee_code   text not null unique,
    name            text not null,
    email           text not null unique,
    department      text,
    designation     text,
    role            text not null default 'employee'
                        check (role in ('employee', 'admin', 'super_admin')),
    joining_date    date,
    is_active       boolean not null default true,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index idx_employees_auth_user_id on employees(auth_user_id);
create index idx_employees_role on employees(role);
create index idx_employees_is_active on employees(is_active);

-- -----------------------------------------------------------------------------
-- attendance
-- One row per employee per calendar day. Uniqueness is enforced here at the
-- database level so duplicate check-ins are impossible even if the API layer
-- has a bug or a client sends repeated requests.
-- -----------------------------------------------------------------------------
create table attendance (
    id                  uuid primary key default gen_random_uuid(),
    employee_id         uuid not null references employees(id) on delete restrict,
    attendance_date     date not null,
    check_in            timestamptz,
    check_out           timestamptz,
    status              text check (status in ('present', 'late', 'absent', 'half_day', 'manual')),
    check_in_source     text check (check_in_source in ('wifi', 'admin')),
    check_out_source    text check (check_out_source in ('wifi', 'admin')),
    check_in_ip         inet,
    check_out_ip        inet,
    marked_by           uuid references employees(id) on delete set null,
    reason              text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint uq_attendance_employee_date unique (employee_id, attendance_date),
    -- If a check_out exists, a check_in must also exist.
    constraint chk_checkout_requires_checkin
        check (check_out is null or check_in is not null),
    -- Admin-sourced records must record who marked them and why.
    constraint chk_admin_source_requires_marker
        check (
            (check_in_source is distinct from 'admin' and check_out_source is distinct from 'admin')
            or (marked_by is not null and reason is not null)
        )
);

create index idx_attendance_employee_date on attendance(employee_id, attendance_date);
create index idx_attendance_date on attendance(attendance_date);
create index idx_attendance_status on attendance(status);

-- -----------------------------------------------------------------------------
-- performance_updates
-- work_date = the day the report is ABOUT. submitted_at = when it was
-- actually submitted. These are never conflated (see README "Performance
-- work date vs submission time").
-- -----------------------------------------------------------------------------
create table performance_updates (
    id                  uuid primary key default gen_random_uuid(),
    employee_id         uuid not null references employees(id) on delete restrict,
    work_date           date not null,
    performance_text    text,
    completed_tasks     text,
    pending_tasks       text,
    blockers            text,
    additional_notes    text,
    status              text not null default 'not_available'
                            check (status in ('not_available', 'available', 'submitted', 'missing', 'backdated')),
    available_from      timestamptz,
    submitted_at        timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint uq_performance_employee_workdate unique (employee_id, work_date)
);

create index idx_performance_employee_workdate on performance_updates(employee_id, work_date);
create index idx_performance_status on performance_updates(status);

-- -----------------------------------------------------------------------------
-- activity_sessions
-- Summarized inactivity periods within an attendance session (NOT raw
-- mouse-movement logs — see README "Privacy requirements").
-- -----------------------------------------------------------------------------
create table activity_sessions (
    id                          uuid primary key default gen_random_uuid(),
    attendance_id               uuid not null references attendance(id) on delete cascade,
    employee_id                 uuid not null references employees(id) on delete restrict,
    started_at                  timestamptz not null,
    ended_at                    timestamptz,
    duration_seconds            integer,
    counted_duration_seconds    integer,
    created_at                  timestamptz not null default now(),

    constraint chk_ended_after_started
        check (ended_at is null or ended_at >= started_at)
);

create index idx_activity_sessions_attendance on activity_sessions(attendance_id);
create index idx_activity_sessions_employee on activity_sessions(employee_id);

-- -----------------------------------------------------------------------------
-- audit_logs
-- Append-only. No UPDATE/DELETE policy is ever granted to any client role
-- (see 003_rls_policies.sql) — only the backend's service-role connection
-- can insert, and nothing can modify or delete a row afterward.
-- -----------------------------------------------------------------------------
create table audit_logs (
    id              uuid primary key default gen_random_uuid(),
    employee_id     uuid references employees(id) on delete set null,
    attendance_id   uuid references attendance(id) on delete set null,
    action          text not null
                        check (action in (
                            'CHECK_IN', 'CHECK_OUT',
                            'ADMIN_ATTENDANCE_CREATED', 'ADMIN_ATTENDANCE_UPDATED', 'ADMIN_ATTENDANCE_DELETED',
                            'EMPLOYEE_CREATED', 'EMPLOYEE_UPDATED', 'EMPLOYEE_ROLE_CHANGED', 'EMPLOYEE_DISABLED',
                            'COMPANY_SETTINGS_UPDATED'
                        )),
    old_value       jsonb,
    new_value       jsonb,
    performed_by    uuid references employees(id) on delete set null,
    reason          text,
    ip_address      inet,
    created_at      timestamptz not null default now()
);

create index idx_audit_logs_employee on audit_logs(employee_id);
create index idx_audit_logs_created_at on audit_logs(created_at desc);
create index idx_audit_logs_action on audit_logs(action);

-- -----------------------------------------------------------------------------
-- company_settings
-- Single-row runtime configuration a Super Admin can edit from the UI. Env
-- vars (see backend/.env.example) provide the deploy-time bootstrap values;
-- once this row exists, the backend prefers it over env vars for values a
-- Super Admin is allowed to change at runtime (see README "Configuration
-- precedence", added in Phase 4).
-- -----------------------------------------------------------------------------
create table company_settings (
    id                              smallint primary key default 1,
    office_start_time               time not null default '09:00',
    performance_start_time          time not null default '17:00',
    inactivity_start_minutes        integer not null default 10,
    daily_inactivity_flag_minutes   integer not null default 60,
    late_threshold_minutes          integer not null default 15,
    heartbeat_interval_seconds      integer not null default 45,
    timezone                        text not null default 'Asia/Kolkata',
    allowed_ips                     text[] not null default array['103.42.196.118'],
    updated_at                      timestamptz not null default now(),
    updated_by                      uuid references employees(id) on delete set null,

    constraint chk_single_row check (id = 1)
);

-- -----------------------------------------------------------------------------
-- updated_at maintenance trigger, reused across tables
-- -----------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger trg_employees_updated_at
    before update on employees
    for each row execute function set_updated_at();

create trigger trg_attendance_updated_at
    before update on attendance
    for each row execute function set_updated_at();

create trigger trg_performance_updates_updated_at
    before update on performance_updates
    for each row execute function set_updated_at();

create trigger trg_company_settings_updated_at
    before update on company_settings
    for each row execute function set_updated_at();
