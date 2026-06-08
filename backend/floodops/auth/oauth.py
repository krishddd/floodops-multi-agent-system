"""
Google OAuth 2.0 — Authorization Code Flow for web application.

Handles login redirect, callback token exchange, and session management.
Required for Google Workspace API access (Sheets, Drive, Gmail).
"""

from __future__ import annotations

from typing import Optional
from floodops.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.send",
]

# In-memory session store (swap with Redis for production)
_sessions: dict[str, dict] = {}


def get_authorization_url() -> str:
    """Generate Google OAuth authorization URL."""
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for access/refresh tokens."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        tokens = resp.json()

    # Get user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get("https://openidconnect.googleapis.com/v1/userinfo",
                                      headers={"Authorization": f"Bearer {tokens['access_token']}"})
        user_info = user_resp.json() if user_resp.status_code == 200 else {}

    session_id = tokens.get("access_token", "unknown")[:32]
    _sessions[session_id] = {"tokens": tokens, "user": user_info}
    return {"session_id": session_id, "user": user_info}


def get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id)


def clear_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
