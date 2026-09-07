-- Work From Home / Other Site requests and assignments.
create table if not exists remote_work_requests (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    work_mode text not null check (work_mode in ('wfh','other_site')),
    work_date date not null,
    purpose text not null,
    site_name text,
    planned_start time,
    planned_end time,
    status text not null default 'pending' check (status in ('pending','approved','rejected','assigned','started','completed','cancelled','not_approved')),
    assignment_source text not null default 'requested' check (assignment_source in ('requested','admin_assigned')),
    approved_by uuid references employees(id),
    approval_reason text,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(employee_id, work_date)
);
create index if not exists idx_remote_work_employee_date on remote_work_requests(employee_id, work_date);
create index if not exists idx_remote_work_status_date on remote_work_requests(status, work_date);
create trigger trg_remote_work_updated_at before update on remote_work_requests for each row execute function set_updated_at();
alter table remote_work_requests enable row level security;
create policy remote_work_select on remote_work_requests for select using (employee_id = auth_employee_id() or is_admin_or_above());
create policy remote_work_insert on remote_work_requests for insert with check (employee_id = auth_employee_id() or is_admin_or_above());
create policy remote_work_update on remote_work_requests for update using (employee_id = auth_employee_id() or is_admin_or_above()) with check (employee_id = auth_employee_id() or is_admin_or_above());

alter table attendance add column if not exists remote_work_request_id uuid references remote_work_requests(id) on delete set null;
alter table attendance add column if not exists work_location text;
alter table attendance drop constraint if exists attendance_check_in_source_check;
alter table attendance add constraint attendance_check_in_source_check check (check_in_source in ('wifi','admin','gps','remote_wfh','remote_other_site'));
alter table attendance drop constraint if exists attendance_check_out_source_check;
alter table attendance add constraint attendance_check_out_source_check check (check_out_source in ('wifi','admin','gps','remote_wfh','remote_other_site'));

alter table audit_logs drop constraint if exists audit_logs_action_check;
alter table audit_logs add constraint audit_logs_action_check check (action in (
    'CHECK_IN','CHECK_OUT','ADMIN_ATTENDANCE_CREATED','ADMIN_ATTENDANCE_UPDATED','ADMIN_ATTENDANCE_DELETED',
    'EMPLOYEE_CREATED','EMPLOYEE_UPDATED','EMPLOYEE_ROLE_CHANGED','EMPLOYEE_DISABLED','EMPLOYEE_DELETED','EMPLOYEE_ID_OR_EMAIL_CHANGED',
    'COMPANY_SETTINGS_UPDATED','COMPANY_CALENDAR_CREATED','COMPANY_CALENDAR_UPDATED',
    'LEAVE_CREATED','LEAVE_UPDATED','LEAVE_CANCELLED','LEAVE_REQUESTED','LEAVE_APPROVED','LEAVE_REJECTED',
    'ON_DUTY_REQUESTED','ON_DUTY_APPROVED','ON_DUTY_REJECTED','ON_DUTY_STARTED','ON_DUTY_ENDED','ON_DUTY_DIRECT_GRANTED',
    'REMOTE_WORK_REQUESTED','REMOTE_WORK_APPROVED','REMOTE_WORK_REJECTED','REMOTE_WORK_ASSIGNED','REMOTE_WORK_UPDATED','REMOTE_WORK_CANCELLED','REMOTE_WORK_NOT_APPROVED'
));
