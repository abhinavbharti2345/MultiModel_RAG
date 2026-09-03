from fastapi import APIRouter
from app.services.health_tracker import health_tracker

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/ai")
async def get_ai_health():
    """
    Returns the current sanitized status of all AI services.
    """
    return health_tracker.get_status()
