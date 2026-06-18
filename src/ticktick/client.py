import json
import os
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from requests_oauthlib import OAuth2Session

AUTH_URL = "https://ticktick.com/oauth/authorize"
TOKEN_URL = "https://ticktick.com/oauth/token"
REDIRECT_URI = "http://localhost:8080"
SCOPES = ["tasks:read", "tasks:write"]
BASE_URL = "https://api.ticktick.com/open/v1"

CREDS_DIR = Path.home() / "workout-planner" / "data" / ".credentials"
TOKEN_PATH = CREDS_DIR / "ticktick_token.json"


def is_authenticated() -> bool:
    return TOKEN_PATH.exists()


def _load_token() -> Optional[dict]:
    if TOKEN_PATH.exists():
        return json.loads(TOKEN_PATH.read_text())
    return None


def _save_token(token: dict) -> None:
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token))


def _credentials() -> tuple[str, str]:
    client_id = os.environ.get("TICKTICK_CLIENT_ID")
    client_secret = os.environ.get("TICKTICK_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise EnvironmentError(
            "TICKTICK_CLIENT_ID and TICKTICK_CLIENT_SECRET must be set.\n"
            "Run `workout ticktick-auth` for setup instructions."
        )
    return client_id, client_secret


def authenticate() -> bool:
    import webbrowser

    client_id, client_secret = _credentials()
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    oauth = OAuth2Session(client_id, redirect_uri=REDIRECT_URI, scope=SCOPES)
    auth_url, state = oauth.authorization_url(AUTH_URL)

    callback_url = None

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal callback_url
            callback_url = f"http://localhost:8080{self.path}"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>TickTick connected! You can close this tab.</h2>")

        def log_message(self, *args):
            pass

    webbrowser.open(auth_url)
    server = HTTPServer(("localhost", 8080), _Handler)
    server.handle_request()

    if not callback_url:
        return False

    oauth = OAuth2Session(client_id, redirect_uri=REDIRECT_URI, state=state)
    token = oauth.fetch_token(
        TOKEN_URL,
        authorization_response=callback_url,
        client_secret=client_secret,
        # TickTick requires HTTP Basic auth on the token endpoint
        auth=(client_id, client_secret),
    )
    _save_token(token)
    return True


def _session() -> OAuth2Session:
    client_id, client_secret = _credentials()

    def _token_saver(token: dict) -> None:
        _save_token(token)

    return OAuth2Session(
        client_id,
        token=_load_token(),
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs={"client_id": client_id, "client_secret": client_secret},
        token_updater=_token_saver,
    )


def get_or_create_project(name: str = "Workouts") -> str:
    session = _session()
    resp = session.get(f"{BASE_URL}/project")
    resp.raise_for_status()
    for project in resp.json():
        if name.lower() in project.get("name", "").lower():
            return project["id"]
    resp = session.post(f"{BASE_URL}/project", json={"name": name})
    resp.raise_for_status()
    return resp.json()["id"]


def _format_content(session: dict) -> str:
    lines = []
    if session.get("reasoning"):
        lines += [session["reasoning"], ""]
    for i, ex in enumerate(session.get("details", {}).get("exercises", []), 1):
        line = f"{i}. {ex['name']} — {ex['sets']} sets × {ex['reps']} reps"
        if ex.get("notes"):
            line += f"\n   {ex['notes']}"
        lines.append(line)
    return "\n".join(lines)


def _parse_class_time(time_str: str, d: date) -> str:
    """Parse '6:30 AM' or '18:30' into a TickTick dueDate string in PT."""
    import re
    time_str = time_str.strip()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", time_str, re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse time: {time_str}")
    hour, minute = int(m.group(1)), int(m.group(2))
    period = (m.group(3) or "").upper()
    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    # Format in local time with PDT offset (-07:00)
    return f"{d.isoformat()}T{hour:02d}:{minute:02d}:00-07:00"


def push_week_plan(plan: dict, project_name: str = "Workouts") -> list[str]:
    """Push all lift and BJJ sessions to TickTick. Returns titles of created tasks."""
    project_id = get_or_create_project(project_name)
    session_http = _session()
    created = []

    for s in plan.get("sessions", []):
        if s["type"] not in ("lift", "bjj"):
            continue

        d = date.fromisoformat(s["date"])
        day_label = d.strftime("%a %m/%d")
        location = f" @ {s['location']}" if s.get("location") else ""
        title = f"[{day_label}] {s['title']}{location}"
        content = _format_content(s)

        payload: dict = {
            "title": title,
            "content": content,
            "projectId": project_id,
            "timeZone": "America/Los_Angeles",
        }

        class_time = s.get("class_time")
        if s["type"] == "bjj" and class_time:
            payload["dueDate"] = _parse_class_time(class_time, d)
            payload["isAllDay"] = False
        else:
            payload["dueDate"] = f"{d.isoformat()}T00:00:00+00:00"
            payload["isAllDay"] = True

        resp = session_http.post(f"{BASE_URL}/task", json=payload)
        resp.raise_for_status()
        created.append(title)

    return created
