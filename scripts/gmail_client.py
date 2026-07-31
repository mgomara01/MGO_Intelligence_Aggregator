"""
gmail_client.py — Gmail API helper for the Alvarez Intelligence Brief pipeline.

Auth: reads the GMAIL_CREDENTIALS_JSON environment variable (the token.json
contents produced by authorize_gmail.py — includes refresh_token, so this
auto-refreshes and never needs the browser consent flow again).
"""
import base64
import json
import os
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

_service = None


def _get_service():
    global _service
    if _service is not None:
        return _service

    creds_info = json.loads(os.environ["GMAIL_CREDENTIALS_JSON"])
    creds = Credentials.from_authorized_user_info(creds_info)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    _service = build("gmail", "v1", credentials=creds)
    return _service


def search_messages(query: str, max_results: int = 5) -> list:
    """Search Gmail with a standard Gmail search query string.
    Returns a list of {"id": ...} dicts (Gmail message IDs)."""
    service = _get_service()
    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return result.get("messages", [])


def _extract_body(payload: dict) -> str:
    """Walk the MIME payload and pull out text/html (preferred) or text/plain."""
    if payload.get("mimeType") in ("text/html", "text/plain") and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    html_fallback = None
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/html" and "data" in part.get("body", {}):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
        if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
            html_fallback = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
        if "parts" in part:  # nested multipart
            nested = _extract_body(part)
            if nested:
                return nested
    return html_fallback or ""


def fetch_message_body(message_id: str) -> str:
    """Fetch one message by ID and return its plain/html body text."""
    service = _get_service()
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    return _extract_body(msg["payload"])


def send_html_email(to: str, subject: str, html_body: str) -> None:
    """Send an HTML email via the Gmail API (requires gmail.send scope)."""
    service = _get_service()
    message = MIMEText(html_body, "html")
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
