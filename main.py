"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
settings = get_settings()
app = FastAPI(title="Company Attendance & Performance API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_allowed_origins, allow_credentials=True,
                   allow_methods=["GET","POST","PUT","DELETE","OPTIONS"], allow_headers=["Authorization","Content-Type"])
@app.get("/health")
def health_check():
    return {"status":"ok","environment":settings.environment}
from app.routers import activity, admin, attendance, auth, calendar, employees, performance  # noqa: E402
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(attendance.router, prefix="/api/attendance", tags=["attendance"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
app.include_router(employees.router, prefix="/api/admin/employees", tags=["employees"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["calendar"])
