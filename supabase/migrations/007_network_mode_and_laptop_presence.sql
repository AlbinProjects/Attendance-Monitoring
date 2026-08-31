-- =============================================================================
-- Migration 007: Admin-configurable network mode + laptop presence
--
-- Phase 14: two additions on top of Phase 13's GPS attendance system,
-- both driven by Super Admin configuration rather than hard-coded env
-- vars:
--
-- 1. `network_mode` lets a Super Admin choose, per company, whether
--    attendance also requires an IP match (companies with a genuine
--    static IP) on top of GPS, or GPS alone (companies on dynamic
--    IP/CGNAT, e.g. this company's current situation — see Phase 13).
--    'static' mode requires BOTH the IP allowlist match AND GPS
--    verification to pass; 'dynamic' mode requires GPS only.
--    Office location (`office_latitude`/`office_longitude`/
--    `office_gps_radius_meters`/`max_gps_accuracy_meters`) becomes
--    runtime-editable here too, following the same DB-overrides-env
--    precedence pattern established for `allowed_ips` in Phase 4.
--
-- 2. `laptop_presence` tracks a lightweight "is the employee's laptop
--    currently open on the app" signal, independent of any attendance
--    record (it has to be — check-in is what CREATES the attendance
--    record, so this can't be keyed off attendance_id). Phone check-in
--    requires a recent laptop_presence row before it succeeds — see
--    backend/app/services/attendance_service.py.
--
-- Purely additive: no existing columns, constraints, or rows are altered
-- or dropped.
-- =============================================================================

alter table company_settings
    add column network_mode                      text not null default 'dynamic'
        check (network_mode in ('static', 'dynamic')),
    add column office_latitude                    double precision,
    add column office_longitude                   double precision,
    add column office_gps_radius_meters            integer,
    add column max_gps_accuracy_meters             integer,
    add column laptop_presence_freshness_minutes   integer not null default 5;

comment on column company_settings.network_mode is
    'static: attendance requires BOTH an IP allowlist match AND GPS verification. dynamic: GPS verification only (no fixed company IP available). Set by a Super Admin via the Company Settings page.';
comment on column company_settings.office_latitude is
    'Runtime override for OFFICE_LATITUDE env var. NULL means "use the env var default" — see app/services/company_config_service.py for the precedence logic.';
comment on column company_settings.laptop_presence_freshness_minutes is
    'How recently the employee''s laptop must have pinged the app for phone check-in to be allowed (see laptop_presence table below).';

-- -----------------------------------------------------------------------------
-- laptop_presence
-- One row per employee, upserted by a periodic ping from the web app
-- while open on a non-phone device (see frontend/src/hooks/useLaptopPresence.js).
-- Deliberately NOT tied to attendance_id — this has to exist BEFORE
-- check-in creates the attendance record, since check-in is gated on it.
-- -----------------------------------------------------------------------------
create table laptop_presence (
    employee_id     uuid primary key references employees(id) on delete cascade,
    last_seen_at    timestamptz not null,
    updated_at      timestamptz not null default now()
);

create trigger trg_laptop_presence_updated_at
    before update on laptop_presence
    for each row execute function set_updated_at();

alter table laptop_presence enable row level security;

create policy laptop_presence_select on laptop_presence
    for select
    using (
        employee_id = auth_employee_id()
        or is_admin_or_above()
    );

create policy laptop_presence_insert_own on laptop_presence
    for insert
    with check (employee_id = auth_employee_id());

create policy laptop_presence_update_own on laptop_presence
    for update
    using (employee_id = auth_employee_id())
    with check (employee_id = auth_employee_id());

-- No delete policy — a stale presence row is harmless (freshness is
-- checked by timestamp on read, not by row existence alone).
