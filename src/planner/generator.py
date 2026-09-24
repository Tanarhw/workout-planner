import json
import os
from datetime import date, timedelta

import anthropic

USER_PROFILE = """
User Profile:
- Primary goal (current phase): UPPER BODY HYPERTROPHY — build size and look great for summer. Think Jeff Nippard, Mike Israetel, AthleanX philosophy: evidence-based progressive overload, high stimulus-to-fatigue ratio exercises, full ROM, mind-muscle connection, weekly volume in the MAV range per muscle group
- Secondary goal: functional strength that transfers to BJJ — pulling strength (rows, pull-ups) for grips/clinch, rotator cuff health, lat strength for guard, core stability
- Running is reduced to easy maintenance mileage only for the next several weeks — legs are low priority
- Training frequency: 5-6 days/week active across BJJ and lifting (minimal running)
- Gym (Bay Club SF): Full commercial gym — barbells, cables, machines, full dumbbell rack
- Home: Dumbbells up to 30lb, two 45lb kettlebells, 30lb ruck plate, pull-up bar, resistance bands
- Travel: Resistance bands + bodyweight only
"""

SYSTEM_PROMPT = f"""You are an evidence-based strength and hypertrophy coach, drawing on Jeff Nippard, Mike Israetel, and AthleanX principles.

{USER_PROFILE}

Programming rules:
- Upper body is the PRIORITY. Bias toward chest, back, shoulders, arms every week
- Hypertrophy rep ranges: 8-15 reps, 3-4 working sets per exercise. Use heavier compounds (6-10) and lighter isolation (12-20)
- 5-7 exercises per session for gym sessions, 4-5 for home
- Weekly volume targets (approximate): Chest 12-16 sets, Back 14-18 sets, Shoulders 12-16 sets, Biceps 10-14 sets, Triceps 10-14 sets — spread across the week
- Include high SFR exercises: cables and machines for isolation (constant tension), barbells/dumbbells for compounds
- BJJ-specific: prioritize rows, pull-ups, face pulls, and rotator cuff work — these directly carry over to grappling
- BJJ counts as significant upper-body fatigue — on BJJ days keep lifting lighter and avoid crushing the same muscles
- Legs: only include if there's a clear open day with no run or BJJ the next day — not a priority this phase
- ABS: always include 2 ab exercises at the end of every lift session. Rotate through: Cable Crunch, Hanging Leg Raise, Ab Wheel Rollout, Plank, Hollow Body Hold, Bicycle Crunch. 3 sets each, 10-20 reps
- NEVER schedule heavy legs the day after a race or long run
- At home: dumbbells, kettlebells, pull-up bar variations, bands
- At the gym: mix cables, machines, and free weights for variety and joint health
- Return 3-5 lifting sessions per week when schedule allows
"""


def _build_weight_context() -> str:
    """Pull recent session logs and format as context for Claude."""
    try:
        from src.db import list_session_logs
        logs = list_session_logs(limit=10)
        if not logs:
            return ""
        lines = ["Recent logged weights (use for progressive overload notes):"]
        for log in logs:
            lines.append(f"\n  {log['date']} — {log['title']}")
            for ex in log["exercises"]:
                weight = ex.get("weight", "")
                reps = ex.get("reps_done", "")
                if weight:
                    lines.append(f"    • {ex['name']}: {weight}" + (f" × {reps}" if reps else ""))
        return "\n".join(lines)
    except Exception:
        return ""


def generate_plan(
    week_start: date,
    run_sessions: list[dict],
    bjj_sessions: list[dict],
    location_pref: str = "gym",
    extra_notes: str = "",
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Add it to your shell profile:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)

    runs_text = "\n".join(
        f"  - {r['date']} ({date.fromisoformat(r['date']).strftime('%A')}): {r['title']}"
        for r in run_sessions
    ) or "  None scheduled"

    bjj_text = "\n".join(
        f"  - {b['date']} ({date.fromisoformat(b['date']).strftime('%A')}): BJJ"
        for b in bjj_sessions
    ) or "  None scheduled"

    week_dates = [
        f"{(week_start + timedelta(days=i)).isoformat()} ({(week_start + timedelta(days=i)).strftime('%A')})"
        for i in range(7)
    ]

    weight_context = _build_weight_context()

    user_message = f"""Plan lifting sessions for the week of {week_start.strftime('%B %d, %Y')}.

Week dates:
{chr(10).join('  ' + d for d in week_dates)}

Scheduled runs:
{runs_text}

Scheduled BJJ:
{bjj_text}

Lifting location preference: {location_pref}
{f'Additional notes: {extra_notes}' if extra_notes else ''}
{weight_context}

Generate 2-4 lifting sessions. Return a JSON object with exactly this structure (no markdown, raw JSON only):
{{
  "sessions": [
    {{
      "date": "YYYY-MM-DD",
      "title": "Short title e.g. Upper Push, Legs, Pull, Full Body KB",
      "location": "gym or home",
      "reasoning": "One sentence why this day/split makes sense given the week",
      "exercises": [
        {{
          "name": "Exercise name",
          "sets": 3,
          "reps": "10-12",
          "notes": "Optional cue or variation"
        }}
      ]
    }}
  ],
  "weekly_notes": "One sentence overall strategy for the week"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=6000,
        thinking={"type": "enabled", "budget_tokens": 3000},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = next((b.text for b in response.content if b.type == "text"), "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:].strip()

    lift_data = json.loads(raw)

    all_sessions = []

    for run in run_sessions:
        all_sessions.append({
            "date": run["date"],
            "day": date.fromisoformat(run["date"]).strftime("%A"),
            "type": "run",
            "title": run["title"],
            "source": run.get("source", "manual"),
            "completed": False,
            "details": {},
        })

    for bjj in bjj_sessions:
        all_sessions.append({
            "date": bjj["date"],
            "day": date.fromisoformat(bjj["date"]).strftime("%A"),
            "type": "bjj",
            "title": "BJJ",
            "source": "manual",
            "class_time": bjj.get("class_time"),
            "completed": False,
            "details": {},
        })

    for lift in lift_data["sessions"]:
        all_sessions.append({
            "date": lift["date"],
            "day": date.fromisoformat(lift["date"]).strftime("%A"),
            "type": "lift",
            "title": lift["title"],
            "source": "ai",
            "location": lift.get("location", "gym"),
            "reasoning": lift.get("reasoning", ""),
            "completed": False,
            "details": {"exercises": lift.get("exercises", [])},
        })

    type_order = {"run": 0, "bjj": 1, "lift": 2}
    all_sessions.sort(key=lambda s: (s["date"], type_order.get(s["type"], 3)))

    return {
        "week_start": week_start.isoformat(),
        "sessions": all_sessions,
        "weekly_notes": lift_data.get("weekly_notes", ""),
    }
