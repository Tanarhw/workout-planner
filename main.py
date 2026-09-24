"""
Workout Planner CLI

Commands:
  auth          Set up Google Calendar OAuth to pull Runna runs
  ticktick-auth Set up TickTick OAuth to push plans as tasks
  strava-auth   Set up Strava OAuth to sync completed runs
  plan          Generate an AI lifting plan around your runs and BJJ
  push          Push a saved week plan to TickTick
  log           Log weights from a completed session
  logs          Show recent weight logs
  view          View a saved week plan
  done          Mark sessions as completed
  history       Show past weeks
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.db import init_db, save_plan, get_plan, list_plans, mark_session_done
from src.display.dashboard import show_week_plan, show_plan_summary, print_plan_text, console

app = typer.Typer(
    name="workout",
    help="Personal weekly workout planner — AI lifting splits around your runs and BJJ",
    add_completion=False,
)


def _this_monday(ref: Optional[date] = None) -> date:
    d = ref or date.today()
    return d - timedelta(days=d.weekday())


def _next_monday(ref: Optional[date] = None) -> date:
    d = ref or date.today()
    days = (7 - d.weekday()) % 7 or 7
    return d + timedelta(days=days)


def _resolve_week(week_arg: Optional[str], upcoming: bool = False) -> date:
    if week_arg:
        return date.fromisoformat(week_arg)
    return _next_monday() if upcoming else _this_monday()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    init_db()
    if ctx.invoked_subcommand is None:
        week_start = _this_monday()
        plan = get_plan(week_start)
        if plan:
            show_week_plan(plan)
        else:
            console.print(
                f"[yellow]No plan for this week ({week_start}).[/yellow]  "
                "Run [bold]workout plan[/bold] to generate one."
            )


@app.command()
def auth() -> None:
    """Set up Google Calendar OAuth to pull your Runna runs automatically."""
    from src.calendar.gcal import CLIENT_SECRETS_PATH, CREDS_DIR, authenticate, is_authenticated

    console.print(Panel(
        "[bold]Google Calendar OAuth Setup[/bold]\n\n"
        "This connects the planner to your Google Calendar so Runna runs are pulled automatically.\n\n"
        "[bold]Steps:[/bold]\n"
        "  1. Go to [cyan]https://console.cloud.google.com[/cyan]\n"
        "  2. Create a new project (or select an existing one)\n"
        "  3. [bold]APIs & Services → Library[/bold] → enable [bold]Google Calendar API[/bold]\n"
        "  4. [bold]APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID[/bold]\n"
        "  5. Application type: [bold]Desktop app[/bold]\n"
        "  6. Download the JSON and save it here:\n"
        f"     [cyan]{CLIENT_SECRETS_PATH}[/cyan]",
        border_style="blue",
        title="Setup",
    ))

    if not CLIENT_SECRETS_PATH.exists():
        console.print(f"\n[yellow]credentials.json not found yet.[/yellow] Complete the steps above, then run [bold]workout auth[/bold] again.")
        raise typer.Exit(1)

    console.print("\n[dim]credentials.json found — opening browser for OAuth...[/dim]")
    if authenticate():
        console.print("[green]Google Calendar connected.[/green]")
    else:
        console.print("[red]Authentication failed. Check your credentials.json and try again.[/red]")
        raise typer.Exit(1)


@app.command()
def plan(
    week: Annotated[Optional[str], typer.Option("--week", "-w", help="Week start date YYYY-MM-DD (default: next Monday)")] = None,
    home: Annotated[bool, typer.Option("--home", help="Prefer home workouts")] = False,
    notes: Annotated[Optional[str], typer.Option("--notes", "-n", help="Extra guidance for Claude")] = None,
) -> None:
    """Generate an AI lifting plan for the week around your runs and BJJ."""
    from src.calendar.gcal import fetch_week_events, parse_run_events, is_authenticated

    week_start = _resolve_week(week, upcoming=True)
    console.print(f"\n[bold]Planning week of {week_start.strftime('%B %d, %Y')}[/bold]\n")

    # --- Runs ---
    run_sessions: list[dict] = []
    if is_authenticated():
        console.print("[dim]Fetching runs from Google Calendar...[/dim]")
        try:
            events, cal_id = fetch_week_events(week_start)
            cal_label = "Runna" if cal_id != "primary" else "primary"
            run_sessions = parse_run_events(events)
            if run_sessions:
                console.print(f"[green]Found {len(run_sessions)} run(s) from {cal_label} calendar:[/green]")
                for r in run_sessions:
                    d = date.fromisoformat(r["date"])
                    console.print(f"  [blue]• {d.strftime('%a %m/%d')} — {r['title']}[/blue]")
            else:
                console.print(f"[yellow]No runs found in {cal_label} calendar this week.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Calendar fetch failed: {e}[/yellow]")
    else:
        console.print("[yellow]Google Calendar not connected.[/yellow] Run [bold]workout auth[/bold] to connect it.\n")

    if Confirm.ask("Add or correct runs manually?", default=not bool(run_sessions)):
        console.print("[dim]Enter each run as:  YYYY-MM-DD Title   (blank line to finish)[/dim]")
        while True:
            entry = Prompt.ask("[dim]Run[/dim]", default="").strip()
            if not entry:
                break
            parts = entry.split(" ", 1)
            try:
                run_date = date.fromisoformat(parts[0]).isoformat()
                title = parts[1] if len(parts) > 1 else "Run"
                run_sessions.append({"date": run_date, "title": title, "source": "manual"})
                console.print(f"  [blue]Added: {run_date} — {title}[/blue]")
            except ValueError:
                console.print("[red]Invalid format — use: YYYY-MM-DD Title[/red]")

    # --- BJJ ---
    console.print()
    bjj_sessions: list[dict] = []
    bjj_input = Prompt.ask(
        "BJJ days this week [dim](comma-separated: Mon,Wed or 2026-06-01,2026-06-03)[/dim]",
        default="",
    ).strip()

    if bjj_input:
        day_offset = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        for entry in bjj_input.split(","):
            entry = entry.strip()
            if not entry:
                continue
            key = entry.lower()[:3]
            if key in day_offset:
                bjj_date = (week_start + timedelta(days=day_offset[key])).isoformat()
            else:
                bjj_date = entry
            try:
                d = date.fromisoformat(bjj_date)
                class_time = Prompt.ask(
                    f"  [red]BJJ time on {d.strftime('%A')}[/red] [dim](e.g. 6:30 AM)[/dim]",
                    default="",
                ).strip()
                bjj_sessions.append({
                    "date": bjj_date,
                    "title": "BJJ",
                    "source": "manual",
                    "class_time": class_time or None,
                })
                time_label = f" at {class_time}" if class_time else ""
                console.print(f"  [red]BJJ: {d.strftime('%a %m/%d')}{time_label}[/red]")
            except ValueError:
                console.print(f"[red]Skipping unrecognized date: {entry}[/red]")

    # --- Location ---
    console.print()
    if home:
        location_pref = "home"
    else:
        location_pref = Prompt.ask(
            "Lift at [bold]gym[/bold], [bold]home[/bold], or [bold]mix[/bold]?",
            choices=["gym", "home", "mix"],
            default="gym",
        )

    # --- Generate ---
    console.print()
    console.print("[dim]Generating your lifting plan with Claude...[/dim]\n")

    try:
        from src.planner.generator import generate_plan
        plan_data = generate_plan(
            week_start=week_start,
            run_sessions=run_sessions,
            bjj_sessions=bjj_sessions,
            location_pref=location_pref,
            extra_notes=notes or "",
        )
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Generation failed: {e}[/red]")
        raise typer.Exit(1)

    show_week_plan(plan_data)

    action = Prompt.ask(
        "What next?",
        choices=["save", "regenerate", "cancel"],
        default="save",
    )

    if action == "save":
        save_plan(week_start, plan_data)
        console.print(f"[green]Plan saved for week of {week_start}.[/green]")
        print_plan_text(plan_data)

    elif action == "regenerate":
        extra = Prompt.ask("Anything to change? [dim](tell Claude)[/dim]", default="").strip()
        combined_notes = f"{notes or ''} {extra}".strip()
        console.print("\n[dim]Regenerating...[/dim]\n")
        try:
            from src.planner.generator import generate_plan
            plan_data = generate_plan(
                week_start=week_start,
                run_sessions=run_sessions,
                bjj_sessions=bjj_sessions,
                location_pref=location_pref,
                extra_notes=combined_notes,
            )
        except Exception as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        show_week_plan(plan_data)
        if Confirm.ask("Save this plan?", default=True):
            save_plan(week_start, plan_data)
            console.print(f"[green]Plan saved.[/green]")
            print_plan_text(plan_data)

    else:
        console.print("[dim]Plan discarded.[/dim]")


@app.command()
def view(
    week: Annotated[Optional[str], typer.Option("--week", "-w", help="Week start date YYYY-MM-DD")] = None,
) -> None:
    """View a saved week plan."""
    week_start = _resolve_week(week)
    plan_data = get_plan(week_start)
    if not plan_data:
        console.print(f"[yellow]No plan found for week of {week_start}.[/yellow]")
        raise typer.Exit(1)
    show_week_plan(plan_data)
    print_plan_text(plan_data)


@app.command()
def done(
    week: Annotated[Optional[str], typer.Option("--week", "-w", help="Week start date YYYY-MM-DD")] = None,
) -> None:
    """Mark workout sessions as completed."""
    week_start = _resolve_week(week)
    plan_data = get_plan(week_start)
    if not plan_data:
        console.print(f"[yellow]No plan for week of {week_start}.[/yellow]")
        raise typer.Exit(1)

    sessions = plan_data.get("sessions", [])
    incomplete = [s for s in sessions if not s.get("completed")]

    if not incomplete:
        console.print("[green]All sessions this week are already marked done![/green]")
        return

    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("#", width=3, style="dim")
    table.add_column("Date", width=12)
    table.add_column("Type", width=6)
    table.add_column("Title")

    for i, s in enumerate(incomplete, 1):
        d = date.fromisoformat(s["date"])
        color = {"run": "blue", "bjj": "red", "lift": "green"}.get(s["type"], "white")
        table.add_row(str(i), d.strftime("%a %m/%d"), f"[{color}]{s['type']}[/{color}]", s["title"])

    console.print(table)
    selection = Prompt.ask("Mark done [dim](numbers or 'all')[/dim]", default="").strip()

    if selection.lower() == "all":
        indices = list(range(len(incomplete)))
    else:
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(",") if x.strip()]
        except ValueError:
            console.print("[red]Invalid selection.[/red]")
            raise typer.Exit(1)

    for i in indices:
        if 0 <= i < len(incomplete):
            s = incomplete[i]
            mark_session_done(week_start, s["date"], s["type"])
            console.print(f"[green]✓ {s['title']} ({s['date']})[/green]")


@app.command()
def history() -> None:
    """Show all saved week plans with completion progress."""
    plans = list_plans()
    if not plans:
        console.print("[dim]No plans saved yet.[/dim]")
        return
    show_plan_summary(plans)


@app.command("ticktick-auth")
def ticktick_auth() -> None:
    """Set up TickTick OAuth to push workout plans as tasks."""
    from src.ticktick.client import is_authenticated, authenticate

    console.print(Panel(
        "[bold]TickTick OAuth Setup[/bold]\n\n"
        "This lets the planner push your week's sessions to TickTick as tasks.\n\n"
        "[bold]Steps:[/bold]\n"
        "  1. Go to [cyan]https://developer.ticktick.com/manage[/cyan]\n"
        "  2. Click [bold]Create App[/bold] — name it anything (e.g. Workout Planner)\n"
        "  3. Set OAuth Redirect URL to: [cyan]http://localhost:8080[/cyan]\n"
        "  4. Copy your [bold]Client ID[/bold] and [bold]Client Secret[/bold]\n"
        "  5. Add them to your shell profile:\n"
        "     [dim]export TICKTICK_CLIENT_ID=your_id[/dim]\n"
        "     [dim]export TICKTICK_CLIENT_SECRET=your_secret[/dim]\n"
        "  6. Run [bold]source ~/.zshrc[/bold] then [bold]workout ticktick-auth[/bold] again",
        border_style="blue",
        title="Setup",
    ))

    import os
    if not os.environ.get("TICKTICK_CLIENT_ID") or not os.environ.get("TICKTICK_CLIENT_SECRET"):
        console.print("\n[yellow]TICKTICK_CLIENT_ID / TICKTICK_CLIENT_SECRET not set yet.[/yellow]")
        raise typer.Exit(1)

    console.print("\n[dim]Opening browser for TickTick OAuth...[/dim]")
    if authenticate():
        console.print("[green]TickTick connected.[/green]")
    else:
        console.print("[red]Authentication failed. Check your credentials and try again.[/red]")
        raise typer.Exit(1)


@app.command()
def push(
    week: Annotated[Optional[str], typer.Option("--week", "-w", help="Week start date YYYY-MM-DD")] = None,
    project: Annotated[str, typer.Option("--project", "-p", help="TickTick project name")] = "Workouts",
) -> None:
    """Push a saved week plan to TickTick as tasks."""
    from src.ticktick.client import is_authenticated, push_week_plan

    if not is_authenticated():
        console.print("[yellow]TickTick not connected.[/yellow] Run [bold]workout ticktick-auth[/bold] first.")
        raise typer.Exit(1)

    week_start = _resolve_week(week)
    plan_data = get_plan(week_start)
    if not plan_data:
        console.print(f"[yellow]No plan found for week of {week_start}.[/yellow] Run [bold]workout plan[/bold] first.")
        raise typer.Exit(1)

    console.print(f"\n[dim]Pushing week of {week_start} to TickTick project \"{project}\"...[/dim]\n")

    try:
        created = push_week_plan(plan_data, project_name=project)
    except Exception as e:
        console.print(f"[red]Push failed: {e}[/red]")
        raise typer.Exit(1)

    for title in created:
        console.print(f"[green]✓[/green] {title}")

    console.print(f"\n[green]{len(created)} tasks created in TickTick.[/green]")


@app.command("strava-auth")
def strava_auth() -> None:
    """Set up Strava OAuth to sync completed runs and log workouts."""
    from src.strava.client import authenticate, is_authenticated

    console.print(Panel(
        "[bold]Strava OAuth Setup[/bold]\n\n"
        "This syncs completed runs with real pace/HR data and lets you log\n"
        "strength sessions to Strava automatically.\n\n"
        "[bold]Steps:[/bold]\n"
        "  1. Go to [cyan]https://www.strava.com/settings/api[/cyan]\n"
        "  2. Create an application — set Callback Domain to [bold]localhost[/bold]\n"
        "  3. Copy your [bold]Client ID[/bold] and [bold]Client Secret[/bold]\n"
        "  4. Add them to your shell profile:\n"
        "     [dim]export STRAVA_CLIENT_ID=your_id[/dim]\n"
        "     [dim]export STRAVA_CLIENT_SECRET=your_secret[/dim]\n"
        "  5. Run [bold]source ~/.zshrc[/bold] then [bold]workout strava-auth[/bold] again",
        border_style="orange3",
        title="Setup",
    ))

    if not os.environ.get("STRAVA_CLIENT_ID") or not os.environ.get("STRAVA_CLIENT_SECRET"):
        console.print("\n[yellow]STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET not set yet.[/yellow]")
        raise typer.Exit(1)

    console.print("\n[dim]Opening browser for Strava OAuth...[/dim]")
    if authenticate():
        console.print("[green]Strava connected.[/green]")
    else:
        console.print("[red]Authentication failed.[/red]")
        raise typer.Exit(1)


@app.command()
def log(
    week: Annotated[Optional[str], typer.Option("--week", "-w", help="Week start date YYYY-MM-DD")] = None,
    to_strava: Annotated[bool, typer.Option("--strava", help="Log session to Strava")] = False,
) -> None:
    """Log weights from a completed lift session."""
    from src.db import save_session_log, get_last_session_log

    week_start = _resolve_week(week)
    plan_data = get_plan(week_start)
    if not plan_data:
        console.print(f"[yellow]No plan for week of {week_start}.[/yellow]")
        raise typer.Exit(1)

    lift_sessions = [s for s in plan_data["sessions"]
                     if s["type"] == "lift" and s.get("details", {}).get("exercises")]

    if not lift_sessions:
        console.print("[yellow]No lift sessions with exercises found this week.[/yellow]")
        raise typer.Exit(1)

    from rich.table import Table
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Session")
    for i, s in enumerate(lift_sessions, 1):
        table.add_row(str(i), f"[green]{s['title']}[/green] — {s['date']}")
    console.print(table)

    choice = Prompt.ask("Which session", default="1").strip()
    try:
        session = lift_sessions[int(choice) - 1]
    except (ValueError, IndexError):
        console.print("[red]Invalid selection.[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Logging: {session['title']} ({session['date']})[/bold]")
    console.print("[dim]Enter weight used for each exercise (blank to skip)[/dim]\n")

    log_entries = []
    for ex in session["details"]["exercises"]:
        last = get_last_session_log(session["type"], ex["name"])
        last_hint = f" [dim](last: {last['exercises'][0]['weight']})[/dim]" if last and last.get("exercises") else ""
        weight = Prompt.ask(
            f"  [green]{ex['name']}[/green]{last_hint} — weight",
            default=""
        ).strip()
        if not weight:
            continue
        reps = Prompt.ask(f"    reps/sets completed", default=f"{ex['sets']}×{ex['reps']}").strip()
        log_entries.append({"name": ex["name"], "weight": weight, "reps_done": reps})

    if not log_entries:
        console.print("[dim]Nothing logged.[/dim]")
        return

    save_session_log(date.fromisoformat(session["date"]), session["type"], session["title"], log_entries)
    console.print(f"\n[green]✓ Logged {len(log_entries)} exercises for {session['title']}[/green]")

    if to_strava or Confirm.ask("Log this session to Strava?", default=False):
        from src.strava.client import is_authenticated as strava_authed, log_workout_to_strava
        if not strava_authed():
            console.print("[yellow]Strava not connected — run [bold]workout strava-auth[/bold][/yellow]")
        else:
            desc = "\n".join(f"{e['name']}: {e['weight']} × {e['reps_done']}" for e in log_entries)
            strava_id = log_workout_to_strava(session["title"], date.fromisoformat(session["date"]),
                                              description=desc)
            if strava_id:
                console.print(f"[green]✓ Logged to Strava (activity {strava_id})[/green]")
            else:
                console.print("[yellow]Strava log failed — check connection.[/yellow]")


@app.command()
def logs() -> None:
    """Show recent weight logs."""
    from src.db import list_session_logs
    entries = list_session_logs(limit=20)
    if not entries:
        console.print("[dim]No sessions logged yet. Run [bold]workout log[/bold] after a session.[/dim]")
        return

    from rich.table import Table
    from rich import box as rich_box
    for entry in entries:
        console.print(f"\n[bold]{entry['date']} — {entry['title']}[/bold]")
        for ex in entry["exercises"]:
            console.print(f"  [green]{ex['name']}[/green] — {ex['weight']} × {ex['reps_done']}")


if __name__ == "__main__":
    app()
