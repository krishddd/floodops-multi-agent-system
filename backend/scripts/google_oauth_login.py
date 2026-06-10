"""
Local Google OAuth login — mints and saves a token.json on this machine.

This authenticates YOUR Google identity (the account you log in with) for the
Workspace scopes declared in floodops.auth.oauth.SCOPES (email, Sheets, Drive,
Gmail-send). It is the standard "installed app" desktop flow: a browser opens,
you consent, and refresh/access tokens are written to token.json next to your
credentials.json so the backend can reuse them without re-prompting.

IMPORTANT — this does NOT authenticate Google Maps. The deck.gl basemap uses a
plain Maps JavaScript API *key* (GOOGLE_MAPS_API_KEY / VITE_GOOGLE_MAPS_API_KEY),
not OAuth. Set that key separately in .env.

Prereq (one-time):
    pip install google-auth-oauthlib

Run (from repo root):
    python backend/scripts/google_oauth_login.py

Outputs:
    token.json   (gitignored)  — your saved tokens, reused on subsequent runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Reuse the exact scopes the backend expects, so the saved token is valid for it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from floodops.auth.oauth import SCOPES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
# Accept either the canonical credentials.json or the original download name.
_CANDIDATES = [
    REPO_ROOT / "credentials.json",
    *REPO_ROOT.glob("client_secret_*.json"),
]
TOKEN_PATH = REPO_ROOT / "token.json"


def _find_client_secret() -> Path:
    for path in _CANDIDATES:
        if path.exists():
            return path
    raise SystemExit(
        "No OAuth client file found. Expected credentials.json (or a "
        "client_secret_*.json) at the repo root."
    )


def main() -> None:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit(
            "Missing dependency. Install it first:\n"
            "    pip install google-auth-oauthlib"
        )

    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        print(f"Already authenticated. token.json is valid → {TOKEN_PATH}")
    elif creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        print("Refreshed expired token.")
    else:
        client_secret = _find_client_secret()
        print(f"Using OAuth client: {client_secret.name}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        # Opens a browser; falls back to console if no browser is available.
        creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    info = json.loads(creds.to_json())
    print(f"\nSaved token → {TOKEN_PATH}")
    print(f"Scopes granted: {', '.join(info.get('scopes', SCOPES))}")
    print("\nThis is gitignored. The backend can now load token.json for "
          "Workspace API calls. (Maps still needs its own API key in .env.)")


if __name__ == "__main__":
    main()
