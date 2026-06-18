from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDS_DIR = Path.home() / "workout-planner" / "data" / ".credentials"
TOKEN_PATH = CREDS_DIR / "token.json"
CLIENT_SECRETS_PATH = CREDS_DIR / "credentials.json"

RUN_KEYWORDS = [
    "🏃", "run", "easy", "tempo", "long run", "interval", "recovery run",
    "runna", " km", "mile", "fartlek", "strides", "400", "800", "workout",
]


def _get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_PATH.exists():
                raise FileNotFoundError(
                    f"Google credentials not found at {CLIENT_SECRETS_PATH}\n"
                    "Run `workout auth` for setup instructions."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())

    return creds


def is_authenticated() -> bool:
    return TOKEN_PATH.exists()


def authenticate() -> bool:
    try:
        _get_credentials()
        return True
    except Exception:
        return False


def _get_service():
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=_get_credentials(), cache_discovery=False)


def _find_runna_calendar_id(service) -> str:
    """Return the Runna calendar ID, falling back to primary."""
    calendars = service.calendarList().list().execute().get("items", [])
    for cal in calendars:
        if "runna" in cal.get("summary", "").lower():
            return cal["id"]
    return "primary"


def fetch_week_events(week_start: date) -> list[dict]:
    service = _get_service()
    cal_id = _find_runna_calendar_id(service)

    time_min = datetime.combine(week_start, datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(week_start + timedelta(days=7), datetime.min.time()).isoformat() + "Z"

    result = service.events().list(
        calendarId=cal_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return result.get("items", []), cal_id


def parse_run_events(events: list[dict]) -> list[dict]:
    runs = []
    for event in events:
        title = event.get("summary", "").lower()
        if any(kw in title for kw in RUN_KEYWORDS):
            start = event.get("start", {})
            event_date = start.get("date") or start.get("dateTime", "")[:10]
            runs.append({
                "date": event_date,
                "title": event.get("summary", "Run"),
                "gcal_id": event.get("id", ""),
                "source": "gcal",
            })
    return runs
