from fastapi import APIRouter, Depends
from app.dependencies import require_role
from app.schemas.breaks import StartBreakRequest
from app.services import break_service

router = APIRouter()

@router.get("/today")
async def today(employee: dict = Depends(require_role("employee", "admin"))):
    return break_service.get_today(employee["id"])

@router.post("/start")
async def start(payload: StartBreakRequest, employee: dict = Depends(require_role("employee", "admin"))):
    return break_service.start_break(employee["id"], payload.break_type)

@router.post("/end")
async def end(employee: dict = Depends(require_role("employee", "admin"))):
    return break_service.end_break(employee["id"])
