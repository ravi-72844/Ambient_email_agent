"""Email + calendar back-ends.

EMAIL_BACKEND=mock   (default) -> everything is simulated in memory; safe for demos and tests.
EMAIL_BACKEND=google           -> real Gmail API + Google Calendar API (Milestone 4).

Both back-ends expose the same methods, so the agent code never changes.
"""
import base64
import os
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def resolve_day(day: str) -> date:
    """'wednesday' -> next Wednesday (today counts), '2026-10-20' -> that date, 'today'/'tomorrow' also work."""
    d = day.strip().lower()
    today = date.today()
    if d == "today":
        return today
    if d == "tomorrow":
        return today + timedelta(days=1)
    if d in WEEKDAYS:
        return today + timedelta(days=(WEEKDAYS.index(d) - today.weekday()) % 7)
    return date.fromisoformat(d)   # raises ValueError for garbage


# --------------------------------------------------------------------------- mock
class MockBackend:
    name = "mock"

    def __init__(self):
        self.calendar = {
            "monday": ["10:00-11:00 Team standup", "15:00-16:00 Project review"],
            "tuesday": ["11:00-12:00 Client call"],
            "wednesday": [],
            "thursday": ["14:00-15:00 Sprint planning"],
            "friday": ["09:00-10:00 Standup"],
            "saturday": [],
            "sunday": [],
        }
        self.sent: list[dict] = []
        self.events: list[dict] = []
        self.archived: list[str] = []
        self.flagged: list[str] = []

    def check_availability(self, day: str) -> str:
        key = day.strip().lower()
        if key not in self.calendar:
            try:
                key = WEEKDAYS[resolve_day(day).weekday()]
            except ValueError:
                return f"Unknown day '{day}'. Use a weekday name like 'monday' or a date like 2026-10-20."
        slots = self.calendar[key]
        return f"{day}: busy slots -> {slots}" if slots else f"{day}: completely free"

    def send_email(self, to, subject, body, thread_id=None, message_id=None) -> str:
        self.sent.append({"to": to, "subject": subject, "body": body, "thread_id": thread_id})
        return f"[MOCK] Email sent to {to} with subject '{subject}'."

    def create_event(self, title, day, start_time, duration_minutes=30, attendees=None) -> str:
        self.events.append({"title": title, "day": day, "start_time": start_time,
                            "duration_minutes": duration_minutes, "attendees": attendees or []})
        key = day.strip().lower()
        if key in self.calendar:
            self.calendar[key].append(f"{start_time} {title}")
        return f"[MOCK] Calendar invite '{title}' created on {day} at {start_time} ({duration_minutes} min)."

    def archive(self, message_id) -> str:
        self.archived.append(message_id)
        return f"[MOCK] archived {message_id}"

    def flag(self, message_id) -> str:
        self.flagged.append(message_id)
        return f"[MOCK] flagged {message_id} for the human"

    def fetch_unread(self, max_results=10) -> list[dict]:
        return []


# --------------------------------------------------------------------------- google
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


class GoogleBackend:
    """Real Gmail + Calendar. Needs credentials.json (OAuth 'Desktop app' client) in the project root.
    The first run opens a browser to log in and saves token.json (both files are git-ignored)."""
    name = "google"

    def __init__(self, credentials_file="credentials.json", token_file="token.json"):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(credentials_file):
                    raise FileNotFoundError(
                        "credentials.json not found. See docs/GMAIL_SETUP.md to create it in Google Cloud Console.")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        self.gmail = build("gmail", "v1", credentials=creds)
        self.cal = build("calendar", "v3", credentials=creds)
        self.tz = os.getenv("TIMEZONE", "Asia/Kolkata")

    # ---- Gmail
    def fetch_unread(self, max_results=10) -> list[dict]:
        res = self.gmail.users().messages().list(
            userId="me", q="is:unread in:inbox", maxResults=max_results).execute()
        out = []
        for m in res.get("messages", []):
            msg = self.gmail.users().messages().get(userId="me", id=m["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            out.append({
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "message_id": headers.get("message-id"),
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(no subject)"),
                "body": _extract_body(msg["payload"]) or msg.get("snippet", ""),
            })
        return out

    def send_email(self, to, subject, body, thread_id=None, message_id=None) -> str:
        mime = MIMEText(body)
        mime["to"] = to
        mime["subject"] = subject
        if message_id:                         # makes Gmail show it as a reply in the same thread
            mime["In-Reply-To"] = message_id
            mime["References"] = message_id
        payload = {"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode()}
        if thread_id:
            payload["threadId"] = thread_id
        sent = self.gmail.users().messages().send(userId="me", body=payload).execute()
        return f"Email sent to {to} (gmail id {sent['id']})."

    def archive(self, message_id) -> str:
        self.gmail.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["INBOX", "UNREAD"]}).execute()
        return f"archived {message_id}"

    def flag(self, message_id) -> str:
        self.gmail.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": ["STARRED", "IMPORTANT"]}).execute()
        return f"starred {message_id} for the human"

    def mark_read(self, message_id) -> None:
        self.gmail.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()

    # ---- Calendar
    def check_availability(self, day: str) -> str:
        try:
            d = resolve_day(day)
        except ValueError:
            return f"Unknown day '{day}'. Use a weekday name like 'monday' or a date like 2026-10-20."
        start = datetime.combine(d, datetime.min.time()).isoformat() + "Z"
        end = (datetime.combine(d, datetime.min.time()) + timedelta(days=1)).isoformat() + "Z"
        events = self.cal.events().list(calendarId="primary", timeMin=start, timeMax=end,
                                        singleEvents=True, orderBy="startTime").execute().get("items", [])
        if not events:
            return f"{day} ({d}): completely free"
        slots = [f"{e['start'].get('dateTime', e['start'].get('date'))[11:16]} {e.get('summary', 'busy')}"
                 for e in events]
        return f"{day} ({d}): busy slots -> {slots}"

    def create_event(self, title, day, start_time, duration_minutes=30, attendees=None) -> str:
        d = resolve_day(day)
        hh, mm = [int(x) for x in start_time.split(":")[:2]]
        start = datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm)
        end = start + timedelta(minutes=int(duration_minutes))
        event = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": self.tz},
            "end": {"dateTime": end.isoformat(), "timeZone": self.tz},
            "attendees": [{"email": a} for a in (attendees or [])],
        }
        ev = self.cal.events().insert(calendarId="primary", body=event, sendUpdates="all").execute()
        return f"Calendar event created: {ev.get('htmlLink')}"


def _extract_body(payload) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="ignore")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


_backend = None


def get_backend():
    global _backend
    if _backend is None:
        _backend = GoogleBackend() if os.getenv("EMAIL_BACKEND", "mock").lower() == "google" else MockBackend()
    return _backend


def set_backend(backend) -> None:
    """Used by tests / evaluation scripts to inject a fresh MockBackend."""
    global _backend
    _backend = backend
