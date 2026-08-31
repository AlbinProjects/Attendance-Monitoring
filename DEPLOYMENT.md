# Deployment Guide

This assumes Phases 1–11 are complete: the codebase in this repo, and a
Supabase project you've already run the migrations against (see
[`supabase/README.md`](./supabase/README.md) if you haven't done that
part yet).

Deployment happens in three stages, in this order, because the backend
and frontend each need to know the other's final URL:

1. **Supabase** — already done if you followed `supabase/README.md`.
2. **Backend** (Render, Railway, or a VPS) — deploy first, with a
   temporary/placeholder `CORS_ALLOWED_ORIGINS`.
3. **Frontend** (Vercel) — deploy pointing at the backend's real URL from
   step 2, then **go back and update the backend's `CORS_ALLOWED_ORIGINS`**
   with the frontend's real URL from this step, and redeploy/restart the
   backend.

---

## 1. Backend deployment

The backend is a standard Dockerized FastAPI app (`backend/Dockerfile`).
Any of the three options below work; pick one.

### Option A — Render

1. Push this repo to GitHub/GitLab.
2. In the Render dashboard: **New → Web Service**, connect the repo, set
   **Root Directory** to `backend`.
3. Render auto-detects the `Dockerfile`. Leave build/start commands blank
   (the Dockerfile's `CMD` handles it — Render sets `$PORT` automatically,
   and the Dockerfile already reads `$PORT`).
4. Under **Environment**, add every variable from `backend/.env.example`
   with real values (see "Environment variables" below). Notably:
   `OFFICE_LATITUDE`/`OFFICE_LONGITUDE` are **required** — the backend
   fails to start without them, since attendance can't be GPS-verified
   otherwise. `COMPANY_ALLOWED_IPS` is optional and can be left blank.
   For `CORS_ALLOWED_ORIGINS`, use a placeholder like
   `https://placeholder.vercel.app` for now — you'll update this in step 3.
5. Deploy. Note the resulting URL, e.g. `https://your-app.onrender.com`.
6. Confirm it's up: `curl https://your-app.onrender.com/health` should
   return `{"status":"ok",...}`.

### Option B — Railway

1. **New Project → Deploy from GitHub repo**, select this repo.
2. Set the service's root directory to `backend` (Railway → service
   Settings → Source).
3. Railway also auto-detects the Dockerfile. Add the same environment
   variables as above under the service's **Variables** tab.
4. Deploy and note the generated `*.up.railway.app` URL (or attach a
   custom domain).

### Option C — Any VPS (Docker)

```bash
# On the VPS, with Docker installed:
git clone <your-repo-url>
cd attendance-system/backend
cp .env.example .env
nano .env   # fill in real values

docker build -t attendance-backend .
docker run -d \
  --name attendance-backend \
  --restart unless-stopped \
  --env-file .env \
  -p 8000:8000 \
  attendance-backend

curl http://localhost:8000/health
```

Put a reverse proxy (nginx, Caddy, or Cloudflare) in front of this for
TLS. Whichever proxy you use is the "trusted proxy" — set
`TRUSTED_PROXY_HOP_COUNT` accordingly. This value now only affects
informational IP capture for audit logs (attendance itself is verified by
GPS, not IP — see README "GPS-based attendance verification"), but
getting it wrong still means audit logs record the proxy's IP instead of
the real caller's, so it's worth setting correctly.

> **Note on this project's Dockerfile:** it was validated in this
> environment by running the actual application directly with `uvicorn
> app.main:app --host 0.0.0.0 --port $PORT` (exactly what the Dockerfile's
> `CMD` does) and confirming `/health`, `/docs`, and `/openapi.json` all
> respond correctly. The Docker *build* itself could not be executed in
> this development sandbox (no Docker daemon available here) — run
> `docker build -t attendance-backend backend/` yourself once before your
> first real deployment to catch anything sandbox-specific.

---

## 2. Frontend deployment (Vercel)

1. In the Vercel dashboard: **Add New → Project**, import this repo, set
   **Root Directory** to `frontend`.
2. Framework preset: Vite (auto-detected). Build command `npm run build`,
   output directory `dist` (both auto-detected from `package.json`).
3. Add environment variables (**Project Settings → Environment
   Variables**):

   | Variable | Value |
   |---|---|
   | `VITE_SUPABASE_URL` | Your Supabase project URL |
   | `VITE_SUPABASE_ANON_KEY` | Your Supabase anon (public) key |
   | `VITE_API_BASE_URL` | Your backend's URL + `/api`, e.g. `https://your-app.onrender.com/api` |

4. Deploy. Note the resulting URL, e.g. `https://your-app.vercel.app`.
5. `frontend/vercel.json` (already in this repo) rewrites all paths to
   `index.html`, so refreshing a client-side route like
   `/employee/dashboard` doesn't 404 — Vercel picks this up automatically.

### Now close the loop: update backend CORS

Go back to your backend host (Render/Railway/VPS) and set:

```env
CORS_ALLOWED_ORIGINS=https://your-app.vercel.app
```

Redeploy (Render/Railway) or restart the container (VPS:
`docker restart attendance-backend`). Confirm from a browser devtools
console on the deployed frontend that API calls succeed — a CORS
misconfiguration shows up immediately as a browser console error on the
first request.

If you have a custom domain in front of Vercel, use that domain here
instead (and add it as an additional entry if you keep the `*.vercel.app`
preview domain in use too — comma-separate multiple origins).

---

## 3. Post-deployment checklist

- [ ] `curl https://your-backend/health` returns `200`.
- [ ] Visiting the Vercel URL shows the login page (confirms the frontend
      build and Supabase connection both work).
- [ ] Log in as the Super Admin created in `supabase/README.md` step 5;
      confirm you land on `/admin/dashboard`.
- [ ] `OFFICE_LATITUDE`/`OFFICE_LONGITUDE` are set to the real office's
      coordinates, not placeholder/test values.
- [ ] From a phone, physically standing inside the office, check in as a
      test employee; confirm the location permission prompt appears and
      check-in succeeds.
- [ ] From the same phone, physically well outside `OFFICE_GPS_RADIUS_METERS`
      of the office, confirm check-in correctly returns 403 with "You're
      outside the permitted office area."
- [ ] Confirm denying the browser's location permission produces a clear
      "Location permission is required for attendance" message, not a
      silent failure or a generic error.
- [ ] Log in as Super Admin → Settings, confirm the network mode defaults
      to "Dynamic" and the office coordinates match what you set in
      `OFFICE_LATITUDE`/`OFFICE_LONGITUDE`. Only switch to "Static" if you
      have genuinely confirmed a static public IP — see README "Network
      mode & laptop presence" for the operational risk of getting this
      wrong.
- [ ] From a phone, confirm check-in is blocked with a clear message if
      no laptop has pinged the app recently, and succeeds once you open
      the app on a laptop/desktop browser first.
- [ ] `CORS_ALLOWED_ORIGINS` on the backend does **not** contain `*`.
- [ ] `SUPABASE_SERVICE_ROLE_KEY` is set only on the backend host, never
      in any Vercel environment variable.
- [ ] Row Level Security is enabled on all 6 tables in the Supabase Table
      Editor (see `supabase/README.md` step 4).

---

## Environment variable reference

See `backend/.env.example` and `frontend/.env.example` for the full,
commented list. Summary of what changes between local dev and production:

| Variable | Local dev | Production |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Your real Vercel URL(s) |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Your real backend URL + `/api` |
| `TRUSTED_PROXY_HOP_COUNT` | `1` (or `0` if hitting FastAPI directly) | Match your actual proxy chain (1 for Render/Railway's LB alone; 2 if you additionally put Cloudflare in front) — affects informational IP audit logging only, not attendance authorization |
| `OFFICE_LATITUDE` / `OFFICE_LONGITUDE` | Your test location's coordinates | **Required.** The real office's coordinates — get these from any map service |
| `OFFICE_GPS_RADIUS_METERS` | Loose, for easy local testing | Tuned to your actual building/campus size (see README "GPS-based attendance verification") |
| `COMPANY_ALLOWED_IPS` | Not needed | Optional — no longer required for attendance (see README) |

Everything else can stay the same between environments.
