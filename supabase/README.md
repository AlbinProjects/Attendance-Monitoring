# Supabase Setup

## 1. Create the project

1. Go to [supabase.com](https://supabase.com) → **New project**.
2. Choose a region close to your office (e.g. Mumbai/Singapore for
   `Asia/Kolkata` operations) and set a strong database password.
3. Once provisioned, go to **Project Settings → API** and copy:
   - `Project URL` → `SUPABASE_URL` / `VITE_SUPABASE_URL`
   - `anon public` key → `SUPABASE_ANON_KEY` / `VITE_SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (**backend only, never
     the frontend**)
   - Go to **Project Settings → API → JWT Settings** and copy the JWT
     secret → `SUPABASE_JWT_SECRET`

## 2. Enable email/password authentication

**Authentication → Providers → Email** — enable it. Disable "Confirm email"
only if you want employees to be usable immediately after creation without
a confirmation step (recommended to leave email confirmation ON if
employees will self-register; since employees are created by a Super Admin
in this system, it's reasonable to turn confirmation off and set passwords
directly — see step 5).

## 3. Run the migrations

Open **SQL Editor** in the Supabase dashboard and run the files in this
folder **in order**:

1. `001_schema.sql` — tables, constraints, indexes, triggers
2. `002_functions.sql` — RLS helper functions
3. `003_rls_policies.sql` — Row Level Security policies
4. `004_seed_company_settings.sql` — seeds the single `company_settings` row
5. `005_activity_heartbeats.sql` — activity/inactivity monitoring table (Phase 6)
6. `006_gps_attendance.sql` — GPS location columns on `attendance`, widens the source constraint to allow `'gps'` (Phase 13 — see main README "GPS-based attendance verification")
7. `007_network_mode_and_laptop_presence.sql` — admin-configurable network mode + office location on `company_settings`, new `laptop_presence` table (Phase 14 — see main README "Network mode & laptop presence")

Alternatively, with the Supabase CLI installed and linked to your project:

```bash
supabase link --project-ref YOUR-PROJECT-REF
supabase db push
```

All seven files were validated against a real PostgreSQL 16 instance
(matching Supabase's engine version) during development, including
functional RLS tests confirming: an employee can only see their own row, an
employee cannot promote themselves to admin, an employee cannot insert
attendance directly, an admin can create a manual attendance record with a
reason, duplicate same-day attendance is rejected by the database, an
employee cannot insert a laptop_presence row for another employee, and
audit_logs cannot be written by any client role (including admin) — only by
the backend's service-role connection.

## 4. Confirm RLS is active

**Table Editor** → open each table → the RLS badge should read **"RLS
enabled"** with the policy count matching what's in `003_rls_policies.sql`,
`005_activity_heartbeats.sql`, and `007_network_mode_and_laptop_presence.sql`:
employees: 3, attendance: 3, performance_updates: 5, activity_sessions: 3,
audit_logs: 1, company_settings: 2, activity_heartbeats: 3,
laptop_presence: 3.

## 5. Create the first Super Admin

There's a chicken-and-egg problem: creating an employee row normally
requires an authenticated Super Admin session (Phase 3+), but the very
first Super Admin doesn't exist yet. Bootstrap it manually, once, via the
dashboard:

1. **Authentication → Users → Add user** → enter the Super Admin's email
   and a password (or use "send invite" if email confirmation is enabled).
   Copy the generated **User UID**.
2. **SQL Editor**, run:

   ```sql
   insert into employees (auth_user_id, employee_code, name, email, role, is_active)
   values (
       'PASTE-THE-USER-UID-HERE',
       'SA001',
       'Your Name',
       'your-email@company.com',
       'super_admin',
       true
   );
   ```

3. Log in through the frontend with that email/password once Phase 3 (auth)
   is implemented. From then on, this Super Admin can create further
   employees, admins, and additional super admins through the app itself —
   no more manual SQL should be needed.

## 6. Configuration precedence (env vars vs. `company_settings`)

- `backend/.env` provides the **deploy-time bootstrap defaults** —
  required to start the server at all, and the ultimate fallback if the
  `company_settings` row is ever missing or unreadable.
- The `company_settings` table (seeded by migration 004) is the
  **runtime-adjustable** source of truth. Once the backend is live, a Super
  Admin editing settings in the app (Phase 8) writes to this table, and the
  backend prefers these values over the env var equivalents. This is what
  lets a Super Admin add a second office IP or change the performance
  start time without a redeploy.
- The one exception: Supabase credentials themselves
  (`SUPABASE_URL`/keys/`SUPABASE_JWT_SECRET`) and `CORS_ALLOWED_ORIGINS`
  stay env-var-only, since the backend needs them before it can even query
  `company_settings`.

This precedence logic is implemented in `network_service.py` and the
settings-loading path in Phase 4.
