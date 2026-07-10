"""
ARGOS-2 API — File Upload Endpoint.

POST /api/upload — accepts a single file, validates it, saves it via the
upload service, and returns an opaque upload_id (UUID).  The raw filesystem
path is never exposed to the caller.

user_id=0 is used for all API/Dashboard uploads (single-tenant system with
no per-user sessions on the REST API side).  Telegram uploads go through
POST /telegram/attach which supplies the real Telegram user_id.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.security import verify_api_key
from src.upload import save_upload, validate_upload

router = APIRouter(tags=["Upload"])

_API_USER_ID = 0  # single-tenant sentinel for REST API / Dashboard uploads


@router.post("/api/upload", dependencies=[Depends(verify_api_key)])
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file and receive an opaque upload_id for use in subsequent
    /api/chat/stream or /run requests via the `attachments` field.
    """
    content = await file.read()
    try:
        validate_upload(file.filename or "", len(content))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    upload_id = save_upload(
        user_id=_API_USER_ID,
        filename=file.filename or "upload",
        content=content,
    )
    return {"upload_id": upload_id, "filename": file.filename}
