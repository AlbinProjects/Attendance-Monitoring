-- Salary/attendance classification details for very short checked-out sessions.
alter table salary_calculations
    add column if not exists short_session_full_day_days numeric(6,2) not null default 0 check (short_session_full_day_days >= 0),
    add column if not exists short_session_half_day_days numeric(6,2) not null default 0 check (short_session_half_day_days >= 0),
    add column if not exists lop_days integer not null default 0 check (lop_days >= 0);
