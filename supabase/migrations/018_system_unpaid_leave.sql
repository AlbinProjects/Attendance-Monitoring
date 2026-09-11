-- System-generated unpaid leave does not have a human approver.
-- Allow granted_by to be NULL for automatic 4:00 PM no-check-in records.
alter table employee_leaves
    alter column granted_by drop not null;
