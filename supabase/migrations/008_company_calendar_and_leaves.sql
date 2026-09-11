-- Company calendar and full-day employee leave management.
create table if not exists company_calendar (
    calendar_date date primary key,
    day_type text not null check (day_type in ('working_day','sunday','holiday','other_non_working')),
    is_working_day boolean not null,
    name text,
    created_by uuid references employees(id),
    updated_by uuid references employees(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_company_calendar_working on company_calendar(is_working_day, calendar_date);
create trigger trg_company_calendar_updated_at before update on company_calendar for each row execute function set_updated_at();
alter table company_calendar enable row level security;
create policy company_calendar_select on company_calendar for select using (auth_is_active());
create policy company_calendar_admin_insert on company_calendar for insert with check (is_admin_or_above());
create policy company_calendar_admin_update on company_calendar for update using (is_admin_or_above()) with check (is_admin_or_above());

create table if not exists employee_leaves (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    leave_date date not null,
    leave_type text not null check (leave_type in ('sick','paid','unpaid')),
    status text not null default 'approved' check (status in ('approved','cancelled')),
    is_additional boolean not null default false,
    reason text,
    granted_by uuid references employees(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(employee_id, leave_date)
);
create index if not exists idx_employee_leaves_employee_date on employee_leaves(employee_id, leave_date);
create index if not exists idx_employee_leaves_date on employee_leaves(leave_date, status);
create trigger trg_employee_leaves_updated_at before update on employee_leaves for each row execute function set_updated_at();
alter table employee_leaves enable row level security;
create policy employee_leaves_select on employee_leaves for select using (employee_id = auth_employee_id() or is_admin_or_above());
create policy employee_leaves_admin_insert on employee_leaves for insert with check (is_admin_or_above());
create policy employee_leaves_admin_update on employee_leaves for update using (is_admin_or_above()) with check (is_admin_or_above());

alter table audit_logs drop constraint if exists audit_logs_action_check;
alter table audit_logs add constraint audit_logs_action_check check (action in (
    'CHECK_IN','CHECK_OUT','ADMIN_ATTENDANCE_CREATED','ADMIN_ATTENDANCE_UPDATED','ADMIN_ATTENDANCE_DELETED',
    'EMPLOYEE_CREATED','EMPLOYEE_UPDATED','EMPLOYEE_ROLE_CHANGED','EMPLOYEE_DISABLED','COMPANY_SETTINGS_UPDATED',
    'COMPANY_CALENDAR_CREATED','COMPANY_CALENDAR_UPDATED','LEAVE_CREATED','LEAVE_UPDATED','LEAVE_CANCELLED'
));
