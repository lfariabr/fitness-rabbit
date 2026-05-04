from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from activity_import import build_import_preview


router = APIRouter(prefix="/import/activities", tags=["activity-import"])
templates = Jinja2Templates(directory="templates")


@router.get("")
async def import_activities_page(request: Request):
    return templates.TemplateResponse(
        request,
        "import-activities.html",
        {"request": request},
    )


@router.post("/preview")
async def preview_activities_import(payload: dict):
    csv_text = payload.get("csv_text")
    if not isinstance(csv_text, str):
        return JSONResponse(
            {"error": "`csv_text` must be provided as a string."},
            status_code=400,
        )

    try:
        preview = build_import_preview(csv_text)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return preview
