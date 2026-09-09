-- Half-day leave approval after an employee completes at least four net work hours.
-- It is a distinct leave type and does not consume standard paid/sick balances.
alter table employee_leaves drop constraint if exists employee_leaves_leave_type_check;
alter table employee_leaves add constraint employee_leaves_leave_type_check
    check (leave_type in ('sick','paid','unpaid','half_day'));

-- Preserve compatibility with the original constraint name if the table was
-- created with a different generated name.
do $$
begin
    if exists (select 1 from pg_constraint where conrelid = 'employee_leaves'::regclass and conname = 'employee_leaves_leave_type_check') then
        null;
    end if;
end $$;

-- Make sure audit actions used by the approval workflow remain accepted.
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
