# Company Attendance, Performance & Activity Monitoring System

Internal web application for employee attendance, daily performance
reporting, and system-activity (not "productivity") monitoring, usable from
any phone or desktop browser — no app install required.

## Architecture

```
Employee Phone / Computer
          ↓
       Internet
          ↓
   React Application (Vite, Tailwind, React Router) — deployed on Vercel
          ↓
      FastAPI backend — deployed on Render / Railway / a VPS
          ↓
      Supabase (PostgreSQL + Auth + Row Level Security)
```

The frontend never talks to Postgres directly for anything security-sensitive
(attendance, performance status, roles). It calls FastAPI, which is the only
component holding the Supabase **service role** key. All business rules —
who you are, what time it is, whether you're on the company network — are
decided server-side.

## Project layout

```
backend/
  app/
    main.py            FastAPI app, CORS, router registration
    config.py           Typed settings loaded from environment variables
    dependencies.py      Auth/role dependencies (implemented Phase 3)
    routers/             One file per API area (stubs for now)
    services/             Business logic per domain (stubs for now)
    models/ schemas/       Pydantic/DB models (added Phase 2+)
  tests/
  requirements.txt
  Dockerfile
  .env.example
frontend/
  src/
    pages/               One file per screen (added Phase 7+)
    services/api.js        Axios instance, attaches Supabase auth token
    services/supabase.js    Supabase browser client (anon key only)
    App.jsx, main.jsx
  package.json
  .env.example
```

## GPS-based attendance verification (Phase 13)

Attendance check-in/check-out is verified using the employee's **phone GPS
location**, not a public-IP allowlist. This replaced the original
IP-based design in Phase 13 because the company's ISP uses CGNAT with a
dynamic public IPv4/IPv6 — the office's observed public IP changed
multiple times in a short period, and no static IP was available at any
price point the company was willing to pay. An allowlist keyed to a
public IP that changes unpredictably would either lock out legitimate
attendance or need constant manual updating — neither is workable for a
tool employees rely on every day.

```env
OFFICE_LATITUDE=10.0234
OFFICE_LONGITUDE=76.3487
OFFICE_GPS_RADIUS_METERS=100
MAX_GPS_ACCURACY_METERS=100
```

**This is enforced entirely server-side in FastAPI.** The phone browser
only supplies raw GPS coordinates and an accuracy value via the
[Geolocation API](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API)
(`navigator.geolocation.getCurrentPosition()`) — it never sends a
pre-computed "am I at the office" boolean, and the backend never trusts
one if it did. `app/services/location_service.py` independently computes
the distance (Haversine formula) between the reported coordinates and the
configured office location, and rejects the request if the distance
exceeds `OFFICE_GPS_RADIUS_METERS` or the reported accuracy is worse than
`MAX_GPS_ACCURACY_METERS`.

A few things to understand about this control:

1. **Where the coordinates come from.** `OFFICE_LATITUDE`/`OFFICE_LONGITUDE`
   are required — the app fails to start without them, since attendance
   can't be verified at all otherwise. Find your office's coordinates via
   any map service (right-click the location on Google Maps, for example)
   and use enough decimal precision (4-5 places) for the radius check to
   be meaningful.
2. **The radius and accuracy thresholds are tunable, not universal.** 100m
   is a reasonable starting point for a single building, but a larger
   campus, a very tall building, or a location with poor GPS reception
   indoors may need a larger radius or a more lenient accuracy threshold.
   There's no one-size-fits-all value — adjust based on real employee
   experience after rollout.
3. **GPS does not prove physical presence.** Browser GPS can be spoofed on
   some devices (mock location apps, rooted/jailbroken devices, browser
   dev tools). Accuracy varies significantly, especially indoors. This is
   a practical, low-cost presence signal intended to reduce casual remote
   attendance — not a security-critical control on its own, which is why
   the system layers it with authentication, server-side timestamps,
   unique database constraints, Row Level Security, and audit logging
   rather than relying on it alone. See `SECURITY.md` for the full,
   honest treatment of this limitation.
4. **The employee doesn't need to understand any of this.** The UI never
   asks for or displays raw latitude/longitude — pressing CHECK IN
   triggers a location permission prompt (only at that moment, never
   proactively on page load) and then either succeeds or shows a plain-
   language reason it didn't ("You're outside the permitted office area",
   "Location accuracy is too low — please try again").
5. **Historical IP-based records are untouched.** Attendance rows created
   before Phase 13 (`check_in_source = 'wifi'`) still display correctly;
   nothing was deleted or migrated. New rows use
   `check_in_source = 'gps'` with `check_in_latitude`/`check_in_longitude`/
   `check_in_accuracy_meters`/`check_in_distance_meters` populated instead
   of relying on an IP match. The resolved request IP, if available, is
   still stored as informational/audit metadata alongside the GPS data —
   it just no longer gates whether the request succeeds.
6. **Manual/admin attendance is unaffected.** Admins marking exceptional
   attendance (WiFi/GPS unavailable, forgotten check-in, etc.) never go
   through GPS verification — that flow is inherently exceptional and
   already requires a mandatory reason and full audit trail (see Phase 9).

## Network mode & laptop presence (Phase 14)

A Super Admin can configure two additional things at runtime, from
**Admin → Settings** (no redeploy needed):

**Network mode** — some companies genuinely do have a static IP, and want
the extra assurance of also checking it. A Super Admin can switch between:

- **Dynamic** (default) — GPS verification only, as described above. Use
  this if your office's public IP changes (CGNAT, typical residential/small-
  business ISPs).
- **Static** — requires **both** GPS verification **and** a match against
  a configured IP allowlist. Use this only if your office has a genuine,
  unchanging public IP; if the IP ever changes and the allowlist isn't
  updated, employees will be locked out even with valid GPS, so this mode
  needs more operational care than dynamic mode.

This setting lives in the `company_settings` database table, editable via
`PUT /api/admin/settings` — it takes precedence over the `COMPANY_ALLOWED_IPS`
env var the same way `OFFICE_LATITUDE`/`OFFICE_LONGITUDE` env vars are only
the deploy-time bootstrap default for the office coordinates, which are
also editable from the same settings page.

**Laptop presence** — check-in from the phone additionally requires the
employee's laptop to have had the web app open recently (default: within
the last 5 minutes, configurable). The idea is that both devices are meant
to be in use together — the phone for attendance/GPS, the laptop for
system activity monitoring (Phase 6) — not just the phone alone. The web
app pings a lightweight presence endpoint automatically while open on a
non-phone device (device type is detected heuristically via User-Agent —
documented as an approximate, not perfect, signal). If an employee's
laptop hasn't pinged recently, check-in fails with a clear message telling
them to open the app on their laptop first. This requirement applies to
check-in only, not check-out — by check-out time, genuine laptop activity
monitoring for the day already required real laptop use, a stronger
signal than a fresh ping.

## Environment variables

### Backend (`backend/.env`) — never exposed to the browser

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Public anon key (also used server-side for some calls) |
| `SUPABASE_SERVICE_ROLE_KEY` | **Secret.** Privileged Supabase key. Backend only. |
| `SUPABASE_JWT_SECRET` | Used to verify Supabase Auth tokens |
| `OFFICE_LATITUDE` | **Required.** Office latitude for GPS attendance verification |
| `OFFICE_LONGITUDE` | **Required.** Office longitude for GPS attendance verification |
| `OFFICE_GPS_RADIUS_METERS` | Acceptable distance (meters) from the office for check-in/out |
| `MAX_GPS_ACCURACY_METERS` | Reject GPS readings less precise than this (meters) |
| `COMPANY_ALLOWED_IPS` | *Optional, diagnostic only (Phase 13+).* No longer required or used to gate attendance — see "GPS-based attendance verification" above |
| `TRUSTED_PROXY_HOP_COUNT` | How many reverse-proxy hops to trust when resolving client IP (used for informational IP logging) |
| `OFFICE_TIMEZONE` | e.g. `Asia/Kolkata` — used for all business-time calculations |
| `OFFICE_START_TIME` | e.g. `09:00` |
| `LATE_THRESHOLD_MINUTES` | Grace period before a check-in is marked Late |
| `PERFORMANCE_START_TIME` | e.g. `17:00` — when today's performance form becomes available (not a deadline) |
| `INACTIVITY_START_MINUTES` | Grace period before inactivity starts counting |
| `DAILY_INACTIVITY_FLAG_MINUTES` | Counted-inactivity threshold that flags a session |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origins allowed to call this API |

### Frontend (`frontend/.env`) — public, bundled into the browser build

| Variable | Purpose |
|---|---|
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Public anon key — safe to expose, RLS restricts access |
| `VITE_API_BASE_URL` | URL of the deployed FastAPI backend |

`SUPABASE_SERVICE_ROLE_KEY` must **never** appear in any `VITE_`-prefixed
variable or anywhere in the frontend code/build output.

## Running Phase 1 locally

This phase only stands up the skeleton — no auth, no attendance logic yet.
It confirms both halves of the stack boot and talk to each other.

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in real Supabase values
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/health should return {"status":"ok",...}
```

Note: `Settings` requires real values for `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
`OFFICE_LATITUDE`, and `OFFICE_LONGITUDE` to start (Supabase project
creation happens in Phase 2; GPS office coordinates were added in Phase
13). `COMPANY_ALLOWED_IPS` is optional and can be left unset. Until you
have real Supabase values, you can use placeholder values from
`.env.example` just to confirm the server boots.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # then fill in real Supabase + API URL values
npm run dev
# → http://localhost:5173
```

## Phase plan

1. ✅ Project structure & configuration
2. ✅ Supabase schema & Row Level Security
3. ✅ FastAPI authentication & authorization
4. ✅ Attendance & company network verification (superseded by Phase 13)
5. ✅ Performance system (5 PM availability rule)
6. ✅ Activity/inactivity monitoring
7. ✅ Employee dashboard
8. ✅ Admin dashboard
9. ✅ Manual attendance & audit system
10. ✅ Reports & CSV export
11. ✅ Testing & security review — see [`SECURITY.md`](./SECURITY.md)
12. ✅ Deployment — see [`DEPLOYMENT.md`](./DEPLOYMENT.md)
13. ✅ GPS-based attendance verification — replaced public-IP allowlisting (see "GPS-based attendance verification" above)
14. ✅ Admin-configurable network mode & laptop presence — see "Network mode & laptop presence" above

Each phase was delivered with: what was built, exact files
created/changed, complete code, how to run it, environment variables
touched, how to test it, and known issues.

## Final deliverable checklist

| # | Item | Where |
|---|---|---|
| 1 | Complete project structure | `backend/`, `frontend/`, `supabase/` |
| 2 | Complete React frontend | `frontend/src/` |
| 3 | Complete FastAPI backend | `backend/app/` |
| 4 | Supabase SQL schema | `supabase/migrations/001_schema.sql`, `006_gps_attendance.sql`, `007_network_mode_and_laptop_presence.sql` |
| 5 | RLS policies | `supabase/migrations/003_rls_policies.sql`, `005_activity_heartbeats.sql` |
| 6 | Authentication setup | `backend/app/dependencies.py`, `frontend/src/context/AuthContext.jsx` |
| 7 | GPS location validation (Phase 13; supersedes IP validation) | `backend/app/services/location_service.py` |
| 8 | Attendance system | `backend/app/services/attendance_service.py`, `routers/attendance.py` |
| 9 | Performance system | `backend/app/services/performance_service.py`, `routers/performance.py` |
| 10 | 5 PM performance availability logic | `performance_service.is_performance_available` |
| 11 | Missing previous-day performance system | `performance_service.get_missing_dates` |
| 12 | Activity/inactivity monitoring | `backend/app/services/activity_service.py` |
| 13 | 10-minute inactivity grace logic | `activity_service.record_heartbeat` |
| 14 | 60-minute inactivity flag | `activity_service.get_activity_summary_for_attendance` |
| 15 | Employee dashboard | `frontend/src/pages/EmployeeDashboard.jsx` + related components |
| 16 | Admin dashboard | `frontend/src/pages/admin/` |
| 17 | Manual attendance | `attendance_service.create_manual_attendance`, `update_attendance_by_id` |
| 18 | Audit logging | `backend/app/services/audit_service.py` |
| 19 | CSV reports | `backend/app/services/reports_service.py` |
| 20 | Tests | `backend/tests/` (196 tests, 13 files) |
| 21 | `.env.example` | `backend/.env.example`, `frontend/.env.example` |
| 22 | Dockerfile | `backend/Dockerfile` |
| 23 | README | this file |
| 24 | Vercel deployment instructions | `DEPLOYMENT.md` §2 |
| 25 | FastAPI deployment instructions | `DEPLOYMENT.md` §1 |
| 26 | Supabase setup instructions | `supabase/README.md` |
| 27 | Security checklist | `SECURITY.md` |
| 28 | Privacy limitations | `SECURITY.md` "What this review does NOT claim"; README §"Important limitation of browser activity" (in code comments throughout `activity_service.py`) |

## Security & privacy summary (expanded per-phase)

- No client-trusted `employee_id`, timestamps, roles, or attendance
  source/location-verification result — everything security-relevant is
  derived server-side.
- GPS coordinates and accuracy are the only location data a client can
  supply; the backend always independently computes distance from the
  configured office location and never trusts a client-provided
  verification boolean (Phase 13, `location_service.py`).
- Attendance and performance uniqueness (`employee_id` + date) is enforced
  at the database level, not just in application code.
- Activity monitoring detects only the *fact* of browser interaction
  (mouse/keyboard/touch/scroll events) — never keystrokes, screenshots,
  browser history, or content. It is called "System Activity Monitoring,"
  not "Productivity Monitoring," and its limitations (it can't see activity
  in other applications) are documented for admins.
- `SUPABASE_SERVICE_ROLE_KEY` lives only on the backend host's environment.
