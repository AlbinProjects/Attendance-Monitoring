-- Break tracking: Tea, Lunch and Evening breaks within an attendance session.
create table if not exists break_sessions (
    id uuid primary key default gen_random_uuid(),
    attendance_id uuid not null references attendance(id) on delete cascade,
    employee_id uuid not null references employees(id) on delete restrict,
    break_type text not null check (break_type in ('tea', 'lunch', 'evening')),
    started_at timestamptz not null,
    ended_at timestamptz,
    created_at timestamptz not null default now(),
    constraint chk_break_ended_after_started check (ended_at is null or ended_at >= started_at)
);

create index if not exists idx_break_sessions_attendance on break_sessions(attendance_id, started_at);
create index if not exists idx_break_sessions_employee on break_sessions(employee_id, started_at desc);

alter table break_sessions enable row level security;

drop policy if exists "break_sessions_select_own_or_admin" on break_sessions;
create policy "break_sessions_select_own_or_admin" on break_sessions
for select using (
    employee_id = (select id from employees where auth_user_id = auth.uid())
    or exists (select 1 from employees e where e.auth_user_id = auth.uid() and e.role in ('admin','super_admin') and e.is_active)
);

drop policy if exists "break_sessions_insert_own_or_admin" on break_sessions;
create policy "break_sessions_insert_own_or_admin" on break_sessions
for insert with check (
    employee_id = (select id from employees where auth_user_id = auth.uid())
    or exists (select 1 from employees e where e.auth_user_id = auth.uid() and e.role in ('admin','super_admin') and e.is_active)
);

drop policy if exists "break_sessions_update_own_or_admin" on break_sessions;
create policy "break_sessions_update_own_or_admin" on break_sessions
for update using (
    employee_id = (select id from employees where auth_user_id = auth.uid())
    or exists (select 1 from employees e where e.auth_user_id = auth.uid() and e.role in ('admin','super_admin') and e.is_active)
) with check (
    employee_id = (select id from employees where auth_user_id = auth.uid())
    or exists (select 1 from employees e where e.auth_user_id = auth.uid() and e.role in ('admin','super_admin') and e.is_active)
);

alter table audit_logs drop constraint if exists audit_logs_action_check;
alter table audit_logs add constraint audit_logs_action_check check (action in (
    'CHECK_IN','CHECK_OUT','ADMIN_ATTENDANCE_CREATED','ADMIN_ATTENDANCE_UPDATED','ADMIN_ATTENDANCE_DELETED',
    'EMPLOYEE_CREATED','EMPLOYEE_UPDATED','EMPLOYEE_ROLE_CHANGED','EMPLOYEE_DISABLED','EMPLOYEE_DELETED','EMPLOYEE_ID_OR_EMAIL_CHANGED',
    'COMPANY_SETTINGS_UPDATED','COMPANY_CALENDAR_CREATED','COMPANY_CALENDAR_UPDATED',
    'LEAVE_CREATED','LEAVE_UPDATED','LEAVE_CANCELLED','LEAVE_REQUESTED','LEAVE_APPROVED','LEAVE_REJECTED',
    'ON_DUTY_REQUESTED','ON_DUTY_APPROVED','ON_DUTY_REJECTED','ON_DUTY_STARTED','ON_DUTY_ENDED','ON_DUTY_DIRECT_GRANTED',
    'REMOTE_WORK_REQUESTED','REMOTE_WORK_APPROVED','REMOTE_WORK_REJECTED','REMOTE_WORK_ASSIGNED','REMOTE_WORK_UPDATED','REMOTE_WORK_CANCELLED','REMOTE_WORK_NOT_APPROVED',
    'BREAK_STARTED','BREAK_ENDED'
));
