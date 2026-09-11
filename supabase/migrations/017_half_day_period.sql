-- Distinguish morning vs afternoon half-day leave.
alter table employee_leaves add column if not exists half_day_period text;
alter table employee_leaves drop constraint if exists employee_leaves_half_day_period_check;
alter table employee_leaves add constraint employee_leaves_half_day_period_check
  check (half_day_period is null or half_day_period in ('morning','afternoon'));

-- Existing half-day requests created by the checkout workflow represent
-- employees who worked the morning and left for the afternoon.
update employee_leaves
set half_day_period = 'afternoon'
where leave_type = 'half_day' and half_day_period is null;
