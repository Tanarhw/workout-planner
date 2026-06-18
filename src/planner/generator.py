import json
import os
from datetime import date, timedelta

import anthropic

USER_PROFILE = """
User Profile:
- Goal: Hypertrophy (muscle growth focus — 3-4 sets, 8-15 reps per exercise)
- Training frequency: 5-6 days/week active across running, BJJ, and lifting
- Gym (Bay Club SF): Full commercial gym — barbells, cables, machines, full dumbbell rack
- Home: Dumbbells up to 30lb, two 45lb kettlebells, 30lb ruck plate (for weighted carries/squats), pull-up bar, resistance bands
- Travel: Resistance bands + bodyweight only
"""

SYSTEM_PROMPT = f"""You are a strength and conditioning coach building hypertrophy-focused weekly lifting plans.

{USER_PROFILE}

Programming rules:
- Hypertrophy rep ranges: 8-15 reps, 3-4 working sets per exercise
- 4-6 exercises per session
- NEVER schedule heavy quad-dominant work (squats, leg press) the day before a long run (>10km)
- BJJ counts as full-body — avoid heavy compound upper work the same day as evening BJJ; keep it light or lower body
- Ensure at least one full rest day per week
- Use Push/Pull/Legs or Upper/Lower split depending on available lifting days
- At home: use dumbbells, kettlebells, ruck carries, pull-up bar variations only
- At the gym: mix barbells, cables, and machines for variety and joint health
- Return 2-4 lifting sessions; fewer if run/BJJ volume is high that week
"""


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

    user_message = f"""Plan lifting sessions for the week of {week_start.strftime('%B %d, %Y')}.

Week dates:
{chr(10).join('  ' + d for d in week_dates)}

Scheduled runs:
{runs_text}

Scheduled BJJ:
{bjj_text}

Lifting location preference: {location_pref}
{f'Additional notes: {extra_notes}' if extra_notes else ''}

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
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
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
