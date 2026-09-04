"""
FastAPI application entrypoint.

Phase 1 scope: app instantiation, CORS, health check, and router wiring
placeholders. Auth, attendance, performance, activity, employees, and admin
routers are added in later phases — each router file already exists as a
stub so the project structure is visible from the start.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Company Attendance & Performance API",
    version="0.1.0",
    description=(
        "Internal API for attendance, daily performance, and system "
        "activity monitoring. See README.md for architecture and security "
        "notes."
    ),
)

# CORS: only the configured frontend origin(s) are allowed. Never "*" in
# production — see CORS_ALLOWED_ORIGINS in .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health_check():
    """Unauthenticated liveness check for the hosting platform."""
    return {"status": "ok", "environment": settings.environment}


from app.routers import activity, admin, attendance, auth, employees, performance  # noqa: E402  (import after settings/app setup is intentional)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(attendance.router, prefix="/api/attendance", tags=["attendance"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
app.include_router(employees.router, prefix="/api/admin/employees", tags=["employees"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
