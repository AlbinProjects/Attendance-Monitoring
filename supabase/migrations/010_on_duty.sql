-- On Duty requests and time tracking.
create table if not exists on_duty_requests (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    on_duty_date date not null,
    purpose text not null,
    planned_start time,
    planned_end time,
    status text not null default 'pending' check (status in ('pending','approved','rejected','started','completed','cancelled')),
    approved_by uuid references employees(id),
    approval_reason text,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(employee_id, on_duty_date)
);
create index if not exists idx_on_duty_employee_date on on_duty_requests(employee_id, on_duty_date);
create index if not exists idx_on_duty_status_date on on_duty_requests(status, on_duty_date);
create trigger trg_on_duty_updated_at before update on on_duty_requests for each row execute function set_updated_at();
alter table on_duty_requests enable row level security;
create policy on_duty_select on on_duty_requests for select using (employee_id = auth_employee_id() or is_admin_or_above());
create policy on_duty_insert on on_duty_requests for insert with check (employee_id = auth_employee_id() or is_admin_or_above());
create policy on_duty_update on on_duty_requests for update using (employee_id = auth_employee_id() or is_admin_or_above()) with check (employee_id = auth_employee_id() or is_admin_or_above());

alter table audit_logs drop constraint if exists audit_logs_action_check;
alter table audit_logs add constraint audit_logs_action_check check (action in (
    'CHECK_IN','CHECK_OUT','ADMIN_ATTENDANCE_CREATED','ADMIN_ATTENDANCE_UPDATED','ADMIN_ATTENDANCE_DELETED',
    'EMPLOYEE_CREATED','EMPLOYEE_UPDATED','EMPLOYEE_ROLE_CHANGED','EMPLOYEE_DISABLED','EMPLOYEE_DELETED',
    'EMPLOYEE_ID_OR_EMAIL_CHANGED','COMPANY_SETTINGS_UPDATED','COMPANY_CALENDAR_CREATED','COMPANY_CALENDAR_UPDATED',
    'LEAVE_CREATED','LEAVE_UPDATED','LEAVE_CANCELLED','LEAVE_REQUESTED','LEAVE_APPROVED','LEAVE_REJECTED',
    'ON_DUTY_REQUESTED','ON_DUTY_APPROVED','ON_DUTY_REJECTED','ON_DUTY_STARTED','ON_DUTY_ENDED','ON_DUTY_DIRECT_GRANTED'
));
