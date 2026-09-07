-- =============================================================================
-- Migration 004: Seed company_settings
--
-- Inserts the single settings row with defaults matching backend/.env.example.
-- If you change the office start time, performance start time, inactivity
-- thresholds, or allowed IPs before deploying, edit the values below to
-- match — or just insert with defaults now and change them later from the
-- Super Admin settings screen (built in Phase 8).
-- =============================================================================

insert into company_settings (
    id,
    office_start_time,
    performance_start_time,
    inactivity_start_minutes,
    daily_inactivity_flag_minutes,
    late_threshold_minutes,
    heartbeat_interval_seconds,
    timezone,
    allowed_ips
) values (
    1,
    '09:00',
    '17:00',
    10,
    60,
    15,
    45,
    'Asia/Kolkata',
    array['103.42.196.118']
)
on conflict (id) do nothing;
