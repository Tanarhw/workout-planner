import json
import os
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

BASE_URL = "https://www.strava.com/api/v3"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
REDIRECT_URI = "http://localhost:8080"
SCOPES = "activity:read_all"

CREDS_DIR = Path.home() / "workout-planner" / "data" / ".credentials"
TOKEN_PATH = CREDS_DIR / "strava_token.json"

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def is_authenticated() -> bool:
    return TOKEN_PATH.exists()


def _load_token() -> Optional[dict]:
    if TOKEN_PATH.exists():
        return json.loads(TOKEN_PATH.read_text())
    return None


def _save_token(data: dict) -> None:
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data))


def _credentials() -> tuple[str, str]:
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise EnvironmentError(
            "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set.\n"
            "Run `workout strava-auth` for setup instructions."
        )
    return client_id, client_secret


def _refresh_token() -> dict:
    client_id, client_secret = _credentials()
    token = _load_token()
    resp = httpx.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
    })
    resp.raise_for_status()
    data = resp.json()
    _save_token(data)
    return data


def _get_headers() -> dict:
    token = _load_token()
    if not token:
        raise RuntimeError("Strava not connected — run `workout strava-auth`")
    expires_at = token.get("expires_at", 0)
    if datetime.now(timezone.utc).timestamp() >= expires_at - 300:
        token = _refresh_token()
    return {"Authorization": f"Bearer {token['access_token']}"}


def authenticate() -> bool:
    client_id, _ = _credentials()
    callback_url = None

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal callback_url
            callback_url = f"http://localhost:8080{self.path}"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Strava connected! You can close this tab.</h2>")
        def log_message(self, *args): pass

    params = {"client_id": client_id, "redirect_uri": REDIRECT_URI,
              "response_type": "code", "scope": SCOPES, "approval_prompt": "auto"}
    webbrowser.open(f"{AUTH_URL}?{urlencode(params)}")
    server = HTTPServer(("localhost", 8080), _Handler)
    server.handle_request()

    if not callback_url:
        return False

    qs = parse_qs(urlparse(callback_url).query)
    code = qs.get("code", [None])[0]
    if not code:
        return False

    client_id, client_secret = _credentials()
    resp = httpx.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
    })
    resp.raise_for_status()
    _save_token(resp.json())
    return True


def fetch_week_runs(week_start: date) -> list[dict]:
    """Fetch completed runs from Strava for a given week."""
    headers = _get_headers()
    after = int(datetime.combine(week_start, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
    before = int(datetime.combine(week_start + timedelta(days=7), datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())

    resp = httpx.get(f"{BASE_URL}/athlete/activities", headers=headers,
                     params={"after": after, "before": before, "per_page": 50})
    resp.raise_for_status()

    runs = []
    for act in resp.json():
        if act.get("type") not in RUN_TYPES and act.get("sport_type") not in RUN_TYPES:
            continue
        act_date = act["start_date_local"][:10]
        distance_mi = round(act["distance"] / 1609.34, 1)
        moving_time = act["moving_time"]
        pace_sec = moving_time / (act["distance"] / 1609.34) if act["distance"] > 0 else 0
        pace_min = int(pace_sec // 60)
        pace_s = int(pace_sec % 60)
        hr = act.get("average_heartrate")
        runs.append({
            "date": act_date,
            "title": act.get("name", "Run"),
            "distance_mi": distance_mi,
            "pace": f"{pace_min}:{pace_s:02d}/mi",
            "moving_time_sec": moving_time,
            "avg_hr": hr,
            "strava_id": act["id"],
            "source": "strava",
        })
    return runs


def log_workout_to_strava(title: str, workout_date: date, duration_sec: int = 3600,
                           description: str = "") -> Optional[str]:
    """Create a manual strength activity on Strava."""
    headers = _get_headers()
    headers["Content-Type"] = "application/json"
    start_dt = datetime.combine(workout_date, datetime.min.time().replace(hour=9)).replace(tzinfo=timezone.utc)
    resp = httpx.post(f"{BASE_URL}/activities", headers=headers, json={
        "name": title,
        "sport_type": "WeightTraining",
        "start_date_local": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_time": duration_sec,
        "description": description,
        "trainer": 1,
    })
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    return None
