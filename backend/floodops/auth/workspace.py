"""
Google Workspace API integration — Sheets, Drive, Gmail.

Provides helper functions for logging data to Sheets, uploading reports
to Drive, and sending alert emails via Gmail.
"""

from __future__ import annotations

from typing import Any


async def log_to_sheets(session: dict, spreadsheet_id: str, values: list[list[Any]]) -> dict:
    """Append rows to a Google Sheet for sensor data logging."""
    import httpx
    token = session.get("tokens", {}).get("access_token", "")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/Sheet1!A1:append"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, params={"valueInputOption": "RAW"}, headers={"Authorization": f"Bearer {token}"},
                                  json={"values": values})
        return resp.json() if resp.status_code == 200 else {"error": resp.text}


async def upload_to_drive(session: dict, filename: str, content: bytes, mime_type: str = "application/pdf") -> dict:
    """Upload a flood report to Google Drive."""
    import httpx
    token = session.get("tokens", {}).get("access_token", "")
    metadata = {"name": filename, "mimeType": mime_type}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={"Authorization": f"Bearer {token}"},
            files={"metadata": ("metadata", __import__("json").dumps(metadata).encode(), "application/json"), "file": (filename, content, mime_type)},
        )
        return resp.json() if resp.status_code == 200 else {"error": resp.text}


async def send_alert_email(session: dict, to: str, subject: str, body: str) -> dict:
    """Send an alert email via Gmail API."""
    import base64

    import httpx
    token = session.get("tokens", {}).get("access_token", "")
    message = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
    raw = base64.urlsafe_b64encode(message.encode()).decode()
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                  headers={"Authorization": f"Bearer {token}"}, json={"raw": raw})
        return resp.json() if resp.status_code == 200 else {"error": resp.text}
