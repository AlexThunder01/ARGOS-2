from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.security import get_admin_chat_id, verify_api_key

router = APIRouter(prefix="/telegram/admin", tags=["Telegram Admin"])


class AdminActionRequest(BaseModel):
    admin_chat_id: int
    target_user_id: int
    reason: str = ""


@router.post("/approve", dependencies=[Depends(verify_api_key)])
async def admin_approve_user(req: AdminActionRequest):
    from src.telegram.db import db_approve_user

    if str(req.admin_chat_id) != get_admin_chat_id():
        raise HTTPException(status_code=403, detail="Not admin.")
    db_approve_user(req.target_user_id, approved_by=req.admin_chat_id)
    return {"status": "approved", "user_id": req.target_user_id}


@router.post("/ban", dependencies=[Depends(verify_api_key)])
async def admin_ban_user(req: AdminActionRequest):
    from src.telegram.db import db_ban_user

    if str(req.admin_chat_id) != get_admin_chat_id():
        raise HTTPException(status_code=403, detail="Not admin.")
    db_ban_user(req.target_user_id, reason=req.reason)
    return {"status": "banned", "user_id": req.target_user_id}


@router.get("/users", dependencies=[Depends(verify_api_key)])
async def admin_list_users(status_filter: str = "pending"):
    from src.telegram.db import db_list_users

    if status_filter not in ("pending", "approved", "banned"):
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    return {"users": db_list_users(status_filter)}


@router.get("/suspicious", dependencies=[Depends(verify_api_key)])
async def admin_suspicious_memories(admin_chat_id: int, limit: int = 50, offset: int = 0):
    from src.telegram.db import db_get_suspicious

    if str(admin_chat_id) != get_admin_chat_id():
        raise HTTPException(status_code=403, detail="Not admin.")
    if limit > 100:
        limit = 100
    return {"suspicious": db_get_suspicious(limit=limit, offset=offset)}
