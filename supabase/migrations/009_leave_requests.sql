-- Employee/Admin self-service leave requests with Admin/Super Admin approval.
-- Existing approved/cancelled rows remain valid; new requests use pending/rejected.
alter table employee_leaves drop constraint if exists employee_leaves_status_check;
alter table employee_leaves add constraint employee_leaves_status_check
    check (status in ('pending','approved','rejected','cancelled'));

alter table audit_logs drop constraint if exists audit_logs_action_check;
alter table audit_logs add constraint audit_logs_action_check check (action in (
    'CHECK_IN','CHECK_OUT','ADMIN_ATTENDANCE_CREATED','ADMIN_ATTENDANCE_UPDATED','ADMIN_ATTENDANCE_DELETED',
    'EMPLOYEE_CREATED','EMPLOYEE_UPDATED','EMPLOYEE_ROLE_CHANGED','EMPLOYEE_DISABLED','EMPLOYEE_DELETED',
    'EMPLOYEE_ID_OR_EMAIL_CHANGED','COMPANY_SETTINGS_UPDATED',
    'COMPANY_CALENDAR_CREATED','COMPANY_CALENDAR_UPDATED',
    'LEAVE_CREATED','LEAVE_UPDATED','LEAVE_CANCELLED',
    'LEAVE_REQUESTED','LEAVE_APPROVED','LEAVE_REJECTED'
));
