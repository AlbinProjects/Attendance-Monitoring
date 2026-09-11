-- Monthly salary calculation records for Employees and Admins.
-- Super Admins are intentionally not eligible for salary/attendance calculations.
create table if not exists salary_calculations (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    salary_year integer not null check (salary_year between 2020 and 2100),
    salary_month integer not null check (salary_month between 1 and 12),
    base_salary numeric(12,2) not null check (base_salary > 0),
    total_days_in_month integer not null check (total_days_in_month between 28 and 31),
    elapsed_days_considered integer not null default 0 check (elapsed_days_considered >= 0),
    working_days integer not null default 0,
    holidays integer not null default 0,
    sundays integer not null default 0,
    other_non_working_days integer not null default 0,
    paid_leave_days numeric(6,2) not null default 0,
    sick_leave_days numeric(6,2) not null default 0,
    unpaid_leave_days numeric(6,2) not null default 0,
    unpaid_half_leave_days numeric(6,2) not null default 0,
    other_site_days integer not null default 0,
    on_duty_days integer not null default 0,
    short_8h_days integer not null default 0,
    short_day_penalty_days numeric(6,2) not null default 0,
    deduction_days numeric(8,2) not null default 0,
    per_day_salary numeric(12,2) not null default 0,
    deduction_amount numeric(12,2) not null default 0,
    payable_salary numeric(12,2) not null default 0,
    details jsonb not null default '[]'::jsonb,
    calculated_by uuid references employees(id) on delete set null,
    calculated_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(employee_id, salary_year, salary_month)
);
create index if not exists idx_salary_calculations_employee_month
    on salary_calculations(employee_id, salary_year, salary_month);
create trigger trg_salary_calculations_updated_at
    before update on salary_calculations for each row execute function set_updated_at();

alter table salary_calculations enable row level security;
-- No authenticated-client policies: salary data is available only through the
-- authorized FastAPI backend using its service-role connection.

alter table audit_logs drop constraint if exists audit_logs_action_check;
alter table audit_logs add constraint audit_logs_action_check check (action in (
    'CHECK_IN','CHECK_OUT','ADMIN_ATTENDANCE_CREATED','ADMIN_ATTENDANCE_UPDATED','ADMIN_ATTENDANCE_DELETED',
    'EMPLOYEE_CREATED','EMPLOYEE_UPDATED','EMPLOYEE_ROLE_CHANGED','EMPLOYEE_DISABLED','EMPLOYEE_DELETED','EMPLOYEE_ID_OR_EMAIL_CHANGED',
    'EMPLOYEE_PASSWORD_CHANGED','PASSWORD_CHANGED',
    'COMPANY_SETTINGS_UPDATED','COMPANY_CALENDAR_CREATED','COMPANY_CALENDAR_UPDATED',
    'LEAVE_CREATED','LEAVE_UPDATED','LEAVE_CANCELLED','LEAVE_REQUESTED','LEAVE_APPROVED','LEAVE_REJECTED',
    'ON_DUTY_REQUESTED','ON_DUTY_APPROVED','ON_DUTY_REJECTED','ON_DUTY_STARTED','ON_DUTY_ENDED','ON_DUTY_DIRECT_GRANTED',
    'REMOTE_WORK_REQUESTED','REMOTE_WORK_APPROVED','REMOTE_WORK_REJECTED','REMOTE_WORK_ASSIGNED','REMOTE_WORK_UPDATED','REMOTE_WORK_CANCELLED','REMOTE_WORK_NOT_APPROVED',
    'BREAK_STARTED','BREAK_ENDED',
    'SALARY_CALCULATION_CREATED','SALARY_CALCULATION_UPDATED'
));
