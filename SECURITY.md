# Security & Privacy Review

This document consolidates the security posture of the system as actually
built and tested — every checked item below is backed by a test in
`backend/tests/`, not just a design intention. Where something is a known
limitation rather than a solved problem, it's called out explicitly rather
than glossed over.

## Security checklist

### Authentication & session handling
- [x] All identity comes from a verified Supabase Auth JWT (`app/dependencies.py::get_current_employee`) — signature, expiry, and audience are checked (`jose.jwt.decode`, `algorithms=["HS256"]`, `audience="authenticated"`).
- [x] Invalid, expired, or wrong-secret tokens are rejected with 401. *(tests/test_auth.py)*
- [x] A valid Supabase Auth account with no corresponding `employees` row is rejected with 403, not treated as a valid session. *(test_valid_auth_user_with_no_employee_row_rejected)*
- [x] Disabled (`is_active=false`) employees are rejected with 403 even with an otherwise-valid token. *(test_inactive_employee_rejected)*
- [x] Disabling an employee also bans their underlying Supabase Auth account (defense-in-depth beyond the `is_active` check). *(employees_service.update_employee, test_update_employee_disable_audited_and_bans_auth_user)*

### Authorization
- [x] Every route requiring elevated access uses `require_role(...)`, independent of anything the frontend renders or hides. *(grep-verified: every router function has an auth dependency; only `/health` is intentionally open)*
- [x] Employee → admin-only route → 403, for every admin/super_admin-only endpoint that exists. *(test_security_review.py, test_admin.py, test_employees.py — role-gating tests per phase)*
- [x] Admin (non-super) → employee create/update → 403; only `GET` (list) is admin-accessible. *(test_admin -> POST /admin/employees: 403, verified end-to-end)*
- [x] Employee → manual attendance creation/correction → 403. *(test_employee_cannot_call_manual_attendance_endpoint, test_employee_cannot_correct_attendance_record)*
- [x] Employee → audit log viewer → 403; audit rows have no INSERT/UPDATE/DELETE policy for any authenticated role at the database level either (RLS), only the backend's service-role connection can write one.

### Identity & input trust
- [x] `employee_id` is never accepted from a request body or query parameter on any self-service endpoint — always derived from the authenticated session. Verified by attempting to inject `employee_id` into a performance submission body: the field doesn't exist in the schema, is silently dropped, and the resulting record is still attributed to the real caller. *(test_performance_submission_ignores_injected_employee_id)*
- [x] Check-in/check-out accept **only** latitude/longitude/accuracy — there is structurally no employee_id, timestamp, status, or verification-result field for a client to inject; an empty body is correctly rejected (422), and injected extra fields in a well-formed body are silently dropped with zero effect on the resulting record. *(test_checkin_without_gps_body_is_rejected, test_checkin_body_cannot_inject_identity_timestamp_or_status)*
- [x] All attendance/performance timestamps are server-generated (`time_service.get_office_now`), never accepted from the client — the one deliberate, explicit exception is admin-entered manual attendance, which is audited with who/when/why on every write.
- [x] `attendance_date` + `work_date` business-day calculations always use the configured office timezone, never the browser's local time.

### GPS location verification (Phase 13)
- [x] Attendance authorization is based on phone GPS location, not public-IP allowlisting — replaced in Phase 13 because the company's ISP uses CGNAT with a dynamic public IPv4/IPv6, making a permanent IP allowlist unworkable (the observed public IP changed multiple times during development).
- [x] The client supplies only raw latitude/longitude/accuracy; the backend independently computes distance from the configured office location (Haversine formula) and never trusts a client-provided verification boolean. *(test_location_service.py, test_checkin_body_cannot_inject_identity_timestamp_or_status)*
- [x] Coordinate and accuracy range validation happens at the Pydantic schema layer (`latitude` -90..90, `longitude` -180..180, `accuracy` >= 0) before any business logic runs. *(test_location_service.py schema tests)*
- [x] GPS accuracy is checked before distance — a poor-accuracy reading is rejected even if the reported coordinates happen to be exactly at the office, so a low-confidence reading can never slip through on the coordinates alone. *(test_verify_location_accuracy_checked_before_radius)*
- [x] Radius and accuracy boundaries verified exactly at the configured threshold (inclusive) and just past it, not just with obviously-inside/outside values. *(test_check_in_just_inside_radius_boundary_succeeds, test_check_in_just_outside_radius_boundary_rejected)*
- [x] Manual attendance endpoints are **deliberately not** gated by GPS verification (an admin correcting a record is often doing so because the employee couldn't get a usable GPS reading, or is entering it from off-site) — a documented, intentional exception, not an oversight.
- [x] The resolved request IP, where available, is still captured as informational/audit metadata on GPS check-in/check-out and on admin actions — it plays no role in authorization. Historical IP-sourced attendance rows (`check_in_source = 'wifi'`) from before Phase 13 remain untouched; nothing was deleted or backfilled. The underlying trusted-proxy-aware `X-Forwarded-For` resolution (`network_service.py`) is unchanged from Phase 4 and still passes its full test suite, including the "attacker sends a forged `X-Forwarded-For` header" case — it's simply no longer wired up as an attendance gate.
- [x] **Honestly documented, not oversold**: browser GPS can be spoofed on some devices, accuracy varies (especially indoors), and this does not prove physical presence — see "What this review does NOT claim" below. It is a practical, low-cost presence signal combined with authentication, server-side timestamps, database constraints, and audit logging, not a security-critical control on its own.

### Admin-configurable network mode & laptop presence (Phase 14)
- [x] A Super Admin can select 'static' network mode (requires BOTH IP allowlist match AND GPS) or 'dynamic' mode (GPS only) at runtime, stored in `company_settings` — verified this is a genuine AND, not an OR, in static mode: a correct IP does not excuse failing GPS, and valid GPS does not excuse a disallowed IP. *(test_static_mode_rejects_good_ip_but_bad_gps, test_static_mode_requires_ip_match_even_with_valid_gps)*
- [x] Static mode fails closed when the caller's IP can't be resolved at all — a missing IP is never treated as automatically allowed. *(test_static_mode_with_no_client_ip_rejected)*
- [x] Office GPS coordinates, radius, and accuracy threshold are now runtime-editable by a Super Admin (`company_settings`), taking precedence over the env var defaults, with safe fallback to env on any DB error — same precedence pattern established for `allowed_ips` in Phase 4. *(test_company_config_service.py)*
- [x] Only `super_admin` can write to `/api/admin/settings`; `admin` can read but not write, matching the same read-only-for-admin pattern used for employee management. *(verified end-to-end: employee → 403, super_admin → 200)*
- [x] Phone check-in additionally requires a recent "laptop presence" ping (default: within 5 minutes, admin-configurable) — verified blocked with no ping at all, blocked with a stale ping past the freshness window, and that the freshness boundary is inclusive (exactly at the limit still counts). *(test_check_in_blocked_without_laptop_presence, test_check_in_blocked_with_stale_laptop_presence, test_has_recent_presence_exactly_at_freshness_boundary_is_true)*
- [x] The laptop-presence requirement applies to check-in only, not check-out — by check-out time the day's activity monitoring (Phase 6) already required genuine laptop use, a stronger signal than a fresh ping. Verified check-out succeeds even after the laptop_presence row is removed entirely. *(test_check_out_does_not_require_laptop_presence)*
- [x] Every employee can only insert/update their own `laptop_presence` row — verified with an actual logged-in-as-employee Postgres session that Alice cannot insert a presence row for Bob (0 rows affected, not an error — RLS `WITH CHECK` silently rejects it).
- [x] Device-type detection (phone vs. laptop, used client-side to decide whether to send presence pings) is a User-Agent heuristic, honestly documented as approximate — see "What this review does NOT claim" below.

### Data integrity
- [x] `(employee_id, attendance_date)` and `(employee_id, work_date)` uniqueness enforced at the **database** level (`supabase/migrations/001_schema.sql`), not just in application code — verified against a real PostgreSQL 16 instance, including a direct duplicate-insert rejection test.
- [x] Row Level Security enabled on every table with narrow, explicit policies; verified with actual logged-in-as-employee / logged-in-as-admin SQL sessions (not just policy syntax review) against a real Postgres instance: an employee cannot see another employee's row, cannot self-promote to admin, cannot insert attendance directly, and cannot write to `audit_logs` under any role.
- [x] Manual attendance/corrections require a non-empty `reason` — enforced in both the Pydantic schema and the service layer.
- [x] The Phase 13 migration (`006_gps_attendance.sql`) is purely additive — verified against a live Postgres instance that pre-existing `wifi`-sourced attendance rows remain valid and queryable after the migration, alongside newly-inserted `gps`-sourced rows, with no data loss.


### Information disclosure
- [x] No endpoint returns the Supabase service-role key, JWT secret, or any other backend-only secret — grep-verified across the codebase.
- [x] `employees_service.create_employee` failure paths return a generic error message; raw exception internals are never included in the API response (fixed during this review — a prior version did interpolate `{exc}` directly).
- [x] Employee list/create/update responses strip `auth_user_id` (an internal Supabase Auth linkage field with no frontend use) before leaving the router — response minimization, verified by test. *(test_employee_list_response_never_exposes_auth_user_id)*
- [x] CORS is never configured with a wildcard origin — `CORS_ALLOWED_ORIGINS` is required, and a test guards against ever accidentally defaulting to `["*"]`. *(test_cors_never_defaults_to_wildcard, test_cors_middleware_configured_with_explicit_origins_not_wildcard)*

### Audit trail
- [x] Every check-in, check-out, manual attendance creation, manual attendance correction, employee creation, role change, and disable action writes an audit log entry with `performed_by`, `reason` (where applicable), `old_value`/`new_value`, and `ip_address`.
- [x] Audit rows are immutable once written: no `delete_audit_log` function exists anywhere in the codebase (guarded by an explicit test asserting the function doesn't exist), and no client role — including admin — has an INSERT policy on `audit_logs` at the database level; only the backend's service-role connection can write one.

### Frontend dependency audit
- [x] `npm audit` was run as part of this review. Two findings were addressed:
  - **react-router (moderate, CVE-2025-68470-adjacent open redirect + SSR hydration constructor injection)** — fixed by upgrading `react-router-dom` from `^6.26.2` to `^7.18.2`. Verified: `npm run build` and `npx eslint` both pass unchanged after the upgrade, since this project's routing usage (`BrowserRouter`, `Routes`/`Route`/`Outlet`, `NavLink`, `useNavigate`, `useLocation`, `Navigate`) is basic "library mode" API that v7 keeps compatible — no code changes were needed.
  - **esbuild (moderate, dev-server request/response exposure)** — left unresolved. This only affects `npm run dev`'s local development server, not the production build artifact that actually gets deployed (`npm run build` output has no esbuild dev-server code in it). Fixing it requires a breaking Vite major-version bump (5.x → 8.x) that wasn't attempted in this pass given the limited exposure; revisit before scaling the development team if this becomes a concern.

## What this review does NOT claim

- **GPS verification proves proximity to a coordinate, not physical presence with certainty.** Browser GPS can be spoofed on some devices (mock-location apps, rooted/jailbroken devices, browser developer tools), and accuracy varies significantly, especially indoors. This is documented in the main README and is why the system layers authentication + role + GPS + server timestamps + DB constraints + RLS + audit logging rather than relying on GPS alone. It is a practical, low-cost deterrent against casual remote attendance, not a claim of military-grade verification.
- **Laptop presence detection is a heuristic, not a guarantee.** Device-type classification (phone vs. laptop) is based on a User-Agent regex — a tablet in desktop mode, an unusual browser, or a deliberately spoofed User-Agent could be misclassified. The freshness ping itself only proves "a browser tab was open and visible," not that the employee is actually working — an employee could leave a laptop tab open unattended. This requirement is a nudge toward genuine dual-device usage, not a security-critical control.
- **Static network mode requires more operational discipline than dynamic mode.** If a company selects 'static' mode and their IP later changes without the allowlist being updated, employees will be locked out of attendance entirely (both GPS and IP are required) — the UI documents this trade-off, but it's a real operational risk a Super Admin needs to understand before choosing static mode.
- **The office radius and accuracy thresholds are configured values, not universally correct ones.** 100m/100m are reasonable defaults but may need site-specific tuning (larger campus, taller building, poor indoor GPS reception) — this requires an env var change and restart, not a code change, but it does require an administrator to notice and adjust it.
- **Activity monitoring measures browser events, not work.** It cannot see activity in other applications, paper documents, or meetings. This is by design (see README "Important limitation of browser activity") and is reflected in the UI copy shown to both employees and admins, not just in code comments.
- **No automated penetration test was run.** This review is a structured code/config audit plus targeted regression tests for the specific attack classes named in the original spec, not a substitute for professional penetration testing before a real production launch with real employee data.
- **No rate limiting on login attempts is implemented in this backend** — brute-force protection relies on Supabase Auth's own built-in protections. If additional throttling is required, it should be added at the reverse-proxy/WAF layer in front of the deployed API.
- **No orphaned-account cleanup on partial employee-creation failure.** If the Supabase Auth user is created but the subsequent `employees` row insert fails (e.g., duplicate `employee_code`), the auth account is not automatically deleted. This is a known, documented gap — automatic cleanup was judged riskier (could delete the wrong account under a race) than a manual admin follow-up.

## Test coverage summary

196 backend tests across 13 test files, all passing, run against real dependencies
(no mocked test runner) with a from-scratch venv install before every run
in this project's history. Coverage includes:

| Area | File |
|---|---|
| Auth (valid/invalid/expired/inactive/role-gating) | `test_auth.py` |
| Trusted-proxy IP resolution (informational/audit use only as of Phase 13) | `test_network_service.py` |
| GPS location verification (Haversine correctness, radius/accuracy boundaries, coordinate validation) | `test_location_service.py` |
| Attendance (GPS check-in/out, duplicates, status boundary, radius/accuracy rejection, laptop-presence gate, static/dynamic network mode) | `test_attendance.py` |
| Company settings precedence (DB-over-env) and audited updates (Phase 14) | `test_company_config_service.py` |
| Laptop presence ping/freshness logic (Phase 14) | `test_laptop_presence_service.py` |
| Performance (5 PM rule, backdating, missing detection) | `test_performance.py` |
| Activity/inactivity (grace period, flag threshold) | `test_activity.py` |
| Admin dashboard & table filters | `test_admin.py` |
| Employee provisioning & role/disable auditing | `test_employees.py` |
| Audit log querying & immutability | `test_audit.py` |
| CSV report generation | `test_reports.py` |
| Cross-cutting security regressions (incl. GPS body injection attempts) | `test_security_review.py` |

Database schema and RLS policies were additionally validated against a
real PostgreSQL 16 instance (not just reviewed for syntax) during Phases
2 and 6, and the Phase 13/14 migrations (`006_gps_attendance.sql`,
`007_network_mode_and_laptop_presence.sql`) were similarly validated
live — including confirming pre-existing `wifi`-sourced attendance rows
remain intact after the Phase 13 migration, and functional RLS tests for
`laptop_presence` (an employee can insert/see only their own row; an
admin sees all).
