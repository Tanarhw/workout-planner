from datetime import date, timedelta

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()

TYPE_COLOR = {"run": "blue", "bjj": "red", "lift": "green", "rest": "dim"}
TYPE_ICON = {"run": "Run", "bjj": "BJJ", "lift": "Lift", "rest": "Rest"}


def _session_line(session: dict) -> Text:
    t = session["type"]
    color = TYPE_COLOR.get(t, "white")
    style = f"bold {color}" if not session.get("completed") else f"dim {color} strike"
    done = " [dim]✓[/dim]" if session.get("completed") else ""

    text = Text()
    text.append(f"[{TYPE_ICON.get(t, t.upper())}] ", style=f"bold {color}")
    text.append(session["title"], style=style)
    if session.get("location") and t == "lift":
        text.append(f" @ {session['location']}", style="dim")
    text.append(done)
    return text


def show_week_plan(plan: dict, detailed: bool = True) -> None:
    week_start = date.fromisoformat(plan["week_start"])
    week_end = week_start + timedelta(days=6)

    by_date: dict[str, list] = {}
    for s in plan["sessions"]:
        by_date.setdefault(s["date"], []).append(s)

    table = Table(box=box.ROUNDED, show_header=True, padding=(0, 1), expand=True)
    table.add_column("Day", style="bold", width=11)
    table.add_column("Sessions", ratio=1)
    table.add_column("Exercises", ratio=2)

    for i in range(7):
        day = week_start + timedelta(days=i)
        day_str = day.isoformat()
        label = day.strftime("%a %m/%d")
        sessions = by_date.get(day_str, [])

        if not sessions:
            table.add_row(label, Text("Rest", style="dim"), "")
            continue

        session_lines = Text("\n").join(_session_line(s) for s in sessions)

        detail_parts = []
        if detailed:
            for s in sessions:
                if s["type"] == "lift" and s.get("details", {}).get("exercises"):
                    for i, ex in enumerate(s["details"]["exercises"], 1):
                        line = f"  {i}. {ex['name']} — {ex['sets']} sets × {ex['reps']} reps"
                        if ex.get("notes"):
                            line += f"  [dim italic]({ex['notes']})[/dim italic]"
                        detail_parts.append(f"[dim]{line}[/dim]")
                    if s.get("reasoning"):
                        detail_parts.append(f"[dim italic]  ↳ {s['reasoning']}[/dim italic]")

        table.add_row(label, session_lines, "\n".join(detail_parts))

    notes = plan.get("weekly_notes", "")
    title = f"[bold]Week of {week_start.strftime('%B %d')} – {week_end.strftime('%B %d, %Y')}[/bold]"

    console.print()
    console.print(Panel(
        table,
        title=title,
        subtitle=f"[dim italic]{notes}[/dim italic]" if notes else None,
        border_style="bright_blue",
    ))
    console.print()


def print_plan_text(plan: dict) -> None:
    """Print a clean, copyable plain-text version of the week plan."""
    week_start = date.fromisoformat(plan["week_start"])
    week_end = week_start + timedelta(days=6)

    by_date: dict[str, list] = {}
    for s in plan["sessions"]:
        by_date.setdefault(s["date"], []).append(s)

    console.print()
    console.print(f"[bold]Week of {week_start.strftime('%B %d')} – {week_end.strftime('%B %d, %Y')}[/bold]")
    console.print()

    for i in range(7):
        day = week_start + timedelta(days=i)
        day_str = day.isoformat()
        label = day.strftime("%A %m/%d")
        sessions = by_date.get(day_str, [])

        if not sessions:
            console.print(f"[bold]{label}[/bold] — Rest")
            console.print()
            continue

        for s in sessions:
            t = s["type"]
            color = TYPE_COLOR.get(t, "white")
            location = f" @ {s['location']}" if s.get("location") else ""
            done = " ✓" if s.get("completed") else ""

            if t == "lift":
                console.print(f"[bold]{label} — {s['title']}{location}[/bold]{done}", style=color)
                exercises = s.get("details", {}).get("exercises", [])
                for j, ex in enumerate(exercises, 1):
                    note = f" ({ex['notes']})" if ex.get("notes") else ""
                    console.print(f"  {j}. {ex['name']} — {ex['sets']} sets × {ex['reps']} reps{note}")
            elif t == "bjj":
                console.print(f"[bold]{label} — BJJ[/bold]{done}", style=color)
            elif t == "run":
                console.print(f"[bold]{label} — {s['title']}[/bold]{done}", style=color)

        console.print()


def show_plan_summary(plans: list[dict]) -> None:
    table = Table(title="Saved Week Plans", box=box.SIMPLE_HEAD)
    table.add_column("Week", style="cyan")
    table.add_column("Sessions", justify="center")
    table.add_column("Done", justify="right")

    for p in plans:
        sessions = p.get("sessions", [])
        total = len(sessions)
        done = sum(1 for s in sessions if s.get("completed"))
        week = date.fromisoformat(p["week_start"]).strftime("%b %d, %Y")
        bar = "[green]" + "█" * done + "[/green][dim]" + "░" * (total - done) + "[/dim]"
        table.add_row(week, str(total), f"{done}/{total}  {bar}")

    console.print(table)
