"""Auth routes — Google OAuth login/callback/logout."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from floodops.auth.oauth import clear_session, exchange_code, get_authorization_url, get_session

router = APIRouter()

@router.get("/login")
async def login():
    """Redirect to Google OAuth consent screen."""
    return RedirectResponse(url=get_authorization_url())

@router.get("/callback")
async def callback(code: str):
    """Handle OAuth callback and exchange code for tokens."""
    result = await exchange_code(code)
    return {"status": "authenticated", "user": result.get("user", {}), "session_id": result.get("session_id", "")}

@router.get("/status")
async def auth_status(session_id: str = ""):
    session = get_session(session_id)
    if session:
        return {"authenticated": True, "user": session.get("user", {})}
    return {"authenticated": False}

@router.post("/logout")
async def logout(session_id: str = ""):
    clear_session(session_id)
    return {"status": "logged_out"}
