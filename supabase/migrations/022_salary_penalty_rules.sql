-- Expanded salary penalty tracking.
-- Existing salary_calculations rows remain valid; the new columns default to 0.
alter table salary_calculations
    add column if not exists missed_check_in_days integer not null default 0 check (missed_check_in_days >= 0),
    add column if not exists missed_check_out_days integer not null default 0 check (missed_check_out_days >= 0),
    add column if not exists missed_attendance_events integer not null default 0 check (missed_attendance_events >= 0),
    add column if not exists missed_event_penalty_days numeric(6,2) not null default 0 check (missed_event_penalty_days >= 0);
