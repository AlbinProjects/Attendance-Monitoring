-- Persistent default monthly salary for Employees and Admins.
-- This is the salary used when creating a new monthly calculation, so the
-- administrator does not need to re-enter it every month. Historical
-- salary_calculations rows keep their own base_salary snapshot.
alter table employees
    add column if not exists monthly_salary numeric(12,2)
    check (monthly_salary is null or monthly_salary > 0);

create index if not exists idx_employees_monthly_salary
    on employees(monthly_salary)
    where monthly_salary is not null;

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
    'SALARY_CALCULATION_CREATED','SALARY_CALCULATION_UPDATED','SALARY_BASE_UPDATED'
));
