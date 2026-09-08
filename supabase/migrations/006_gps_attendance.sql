-- =============================================================================
-- Migration 006: GPS attendance verification
--
-- Phase 13: replaces public-IP allowlisting as the REQUIRED attendance
-- authorization mechanism with phone GPS presence verification, because
-- the company's ISP uses CGNAT / dynamic IPv4 and no static IP is
-- available. This migration is purely additive:
--   - New nullable columns on `attendance` for GPS metadata.
--   - The existing check_in_source/check_out_source CHECK constraints are
--     widened to also allow 'gps' (previously only 'wifi'/'admin').
--   - No existing rows, columns, or constraints are dropped or tightened.
--   - Historical check_in_ip/check_out_ip data is left completely intact
--     (see README "Do not delete historical network data").
-- =============================================================================

alter table attendance
    add column check_in_latitude          double precision,
    add column check_in_longitude         double precision,
    add column check_in_accuracy_meters   double precision,
    add column check_in_distance_meters   double precision,
    add column check_out_latitude         double precision,
    add column check_out_longitude        double precision,
    add column check_out_accuracy_meters  double precision,
    add column check_out_distance_meters  double precision;

comment on column attendance.check_in_latitude is
    'Employee-reported GPS latitude at check-in. Untrusted raw input — the backend independently computed check_in_distance_meters from this against the configured office location; this column is kept for audit/debugging, not as an authorization source.';
comment on column attendance.check_in_distance_meters is
    'Server-calculated (Haversine) distance in meters from the configured office location at check-in. This, not the raw coordinates, is what verification was actually based on.';

-- Widen the source constraints to allow 'gps' alongside the existing
-- values. Constraint names below were confirmed against the actual
-- Postgres-assigned names from migration 001 (auto-generated as
-- <table>_<column>_check for unnamed column-level CHECK constraints).
alter table attendance drop constraint attendance_check_in_source_check;
alter table attendance add constraint attendance_check_in_source_check
    check (check_in_source in ('wifi', 'admin', 'gps'));

alter table attendance drop constraint attendance_check_out_source_check;
alter table attendance add constraint attendance_check_out_source_check
    check (check_out_source in ('wifi', 'admin', 'gps'));

-- No RLS policy changes needed: the existing attendance policies
-- (migration 003) already permit employees to select their own rows and
-- admins to insert/update with a reason — the new columns are covered by
-- the same "*" select/insert/update policies without modification.
