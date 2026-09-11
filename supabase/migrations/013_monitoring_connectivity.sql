-- Migration 013: privacy-preserving monitoring connectivity periods.
-- These periods are used to distinguish a lost monitoring connection from
-- employee inactivity. No raw activity or network details are stored.
create table if not exists monitoring_connectivity_periods (
    id uuid primary key default gen_random_uuid(),
    attendance_id uuid not null references attendance(id) on delete cascade,
    employee_id uuid not null references employees(id) on delete restrict,
    started_at timestamptz not null,
    ended_at timestamptz not null,
    reason text not null default 'network_unavailable',
    created_at timestamptz not null default now(),
    check (ended_at >= started_at)
);
create index if not exists idx_monitoring_connectivity_attendance on monitoring_connectivity_periods(attendance_id, started_at);
alter table monitoring_connectivity_periods enable row level security;
create policy monitoring_connectivity_select on monitoring_connectivity_periods for select using (employee_id = auth_employee_id() or is_admin_or_above());
