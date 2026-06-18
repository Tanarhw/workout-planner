# Workout Planner

A personal CLI tool for planning weekly workouts. It pulls your running schedule from Google Calendar (via Runna), lets you add BJJ sessions, and uses Claude AI to generate a hypertrophy-focused lifting split around everything else. Plans are saved locally and pushed to TickTick as due-dated tasks.

## Features

- **Google Calendar integration** — automatically pulls runs from your Runna training plan
- **AI-generated lifting splits** — Claude builds your lifting sessions around your runs and BJJ, respecting recovery, equipment, and location (gym vs. home)
- **TickTick sync** — pushes each session as a task with exercises in the notes, due-dated to the right day, with BJJ classes set to their exact class time
- **Flexible planning** — supports gym, home (kettlebells, dumbbells, pull-up bar), and travel (resistance bands/bodyweight) sessions
- **Local history** — all plans stored in SQLite, viewable and editable week by week

## Setup

### Requirements

- Python 3.12+
- An [Anthropic API key](https://console.anthropic.com/)
- A Google Cloud project with the Calendar API enabled
- A TickTick developer app (for TickTick sync)

### Install

```bash
git clone https://github.com/Tanarhw/workout-planner.git
cd workout-planner
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

Add to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export ANTHROPIC_API_KEY=your_key_here
export TICKTICK_CLIENT_ID=your_ticktick_client_id
export TICKTICK_CLIENT_SECRET=your_ticktick_client_secret
alias workout="~/workout-planner/.venv/bin/workout"
```

### Google Calendar OAuth

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project, enable the **Google Calendar API**
3. Create an **OAuth 2.0 Client ID** (Desktop app type)
4. Download the JSON and save to `data/.credentials/credentials.json`
5. Run `workout auth`

### TickTick OAuth

1. Go to [developer.ticktick.com/manage](https://developer.ticktick.com/manage)
2. Create an app, set the redirect URL to `http://localhost:8080`
3. Add your Client ID and Secret to your shell profile (see above)
4. Run `workout ticktick-auth`

## Usage

```bash
# Generate a plan for next week
workout plan

# Generate for a specific week
workout plan --week 2026-06-15

# Prefer home workouts
workout plan --home

# Pass extra guidance to Claude
workout plan --notes "focus on chest this week"

# View this week's plan
workout view

# Push the plan to TickTick
workout push

# Mark sessions as done
workout done

# Show all past weeks
workout history
```

## Stack

- [Typer](https://typer.tiangolo.com/) — CLI framework
- [Rich](https://github.com/Textualize/rich) — terminal formatting
- [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) — Claude AI for workout generation
- [google-api-python-client](https://github.com/googleapis/google-api-python-client) — Google Calendar
- [requests-oauthlib](https://github.com/requests/requests-oauthlib) — TickTick OAuth
- SQLite — local plan storage
