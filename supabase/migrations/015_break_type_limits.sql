-- Enforce one Tea, one Lunch, and one Evening break per attendance day.
-- Existing duplicate test/legacy rows are preserved; the application blocks
-- new duplicates. The partial unique index only applies to active sessions,
-- while the service-level daily type check prevents a second completed type.
-- This avoids destructive cleanup of historical break records.

create unique index if not exists uq_break_sessions_one_active_per_attendance
on break_sessions(attendance_id)
where ended_at is null;

create index if not exists idx_break_sessions_attendance_type
on break_sessions(attendance_id, break_type);

-- Preserve existing history but prevent any new second use of the same
-- break type for an attendance day. The attendance row lock serializes
-- concurrent starts so two fast clicks cannot create duplicate types.
create or replace function prevent_duplicate_break_type()
returns trigger
language plpgsql
as $$
begin
    perform 1 from attendance where id = new.attendance_id for update;

    if exists (
        select 1
        from break_sessions
        where attendance_id = new.attendance_id
          and break_type = new.break_type
    ) then
        raise exception 'one break type per day';
    end if;

    return new;
end;
$$;

drop trigger if exists trg_prevent_duplicate_break_type on break_sessions;
create trigger trg_prevent_duplicate_break_type
before insert on break_sessions
for each row execute function prevent_duplicate_break_type();
