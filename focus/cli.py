import os
import subprocess
import sys
import click
from datetime import datetime, timedelta

from .config import STATE_DIR
from .utils import parse_duration, normalize_domain, format_duration, parse_time_range, generate_id
from .models import Schedule


def _sudo_run(args):
    """Run a command with sudo. Returns the exit code."""
    result = subprocess.run(["sudo", sys.executable, "-m", "focus"] + args)
    sys.exit(result.returncode)


def _require_install():
    """Check that focus install has been run."""
    if not STATE_DIR.exists():
        click.echo(
            "Focus is not installed yet. Run 'focus install' first.",
            err=True,
        )
        sys.exit(1)


@click.group()
def cli():
    """Focus — unblockable site blocker for macOS."""
    pass


# --- Block list management ---

@cli.command("lists")
def show_lists():
    """Show all block lists."""
    from .store import read_config

    config = read_config()
    lists = config["lists"]

    if not lists:
        click.echo("No block lists defined. Create one with: focus list add <name> <domains...>")
        return

    apps = config.get("apps", {})
    for name, domains in lists.items():
        app_names = apps.get(name, [])
        label = f"{len(domains)} sites"
        if app_names:
            label += f" + {', '.join(app_names)}"
        click.echo(f"\n  {click.style(name, bold=True)} ({label})")
        for d in domains:
            click.echo(f"    - {d}")
        for a in app_names:
            click.echo(f"    - [{a}] (app)")
    click.echo()


@cli.group("list")
def list_group():
    """Manage block lists."""
    pass


@list_group.command("add")
@click.argument("name")
@click.argument("domains", nargs=-1, required=True)
def list_add(name, domains):
    """Create or update a block list.

    Example: focus list add social facebook.com reddit.com twitter.com
    """
    from .store import add_list, get_list

    normalized = [normalize_domain(d) for d in domains]
    existing = get_list(name)

    if existing:
        # Merge with existing domains
        merged = sorted(set(existing + normalized))
        add_list(name, merged)
        new_count = len(merged) - len(existing)
        click.echo(f"Updated '{name}': added {new_count} new domain(s), {len(merged)} total.")
    else:
        add_list(name, sorted(set(normalized)))
        click.echo(f"Created list '{name}' with {len(normalized)} domain(s).")


@list_group.command("remove")
@click.argument("name")
def list_remove(name):
    """Remove an entire block list."""
    from .store import remove_list
    from .blocker import is_list_active

    if is_list_active(name):
        click.echo(f"Cannot remove '{name}': currently in an active block.", err=True)
        sys.exit(1)

    if remove_list(name):
        click.echo(f"Removed list '{name}'.")
    else:
        click.echo(f"List '{name}' not found.", err=True)
        sys.exit(1)


@list_group.command("drop")
@click.argument("name")
@click.argument("domains", nargs=-1, required=True)
def list_drop(name, domains):
    """Remove specific sites from a list.

    Example: focus list drop social facebook.com tumblr.com
    """
    from .store import get_list, add_list

    existing = get_list(name)
    if existing is None:
        click.echo(f"List '{name}' not found.", err=True)
        sys.exit(1)

    to_remove = {normalize_domain(d) for d in domains}
    not_found = to_remove - set(existing)
    if not_found:
        click.echo(f"Not in '{name}': {', '.join(sorted(not_found))}", err=True)

    new_domains = [d for d in existing if d not in to_remove]
    removed = len(existing) - len(new_domains)

    if removed == 0:
        click.echo("Nothing to remove.")
        return

    add_list(name, new_domains)
    click.echo(f"Removed {removed} site(s) from '{name}'. {len(new_domains)} remaining.")


@list_group.command("edit")
@click.argument("name")
def list_edit(name):
    """Open a block list in your $EDITOR for bulk editing.

    Example: focus list edit social
    """
    import tempfile

    from .store import get_list, add_list

    existing = get_list(name)
    if existing is None:
        click.echo(f"List '{name}' not found.", err=True)
        sys.exit(1)

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=f"-focus-{name}.txt", delete=False
    ) as f:
        f.write(f"# Edit domains for '{name}' — one per line\n")
        f.write(f"# Lines starting with # are ignored\n")
        f.write(f"# Save and quit to apply changes\n\n")
        for d in existing:
            f.write(d + "\n")
        tmp_path = f.name

    try:
        result = os.system(f'{editor} "{tmp_path}"')
        if result != 0:
            click.echo("Editor exited with error. No changes made.", err=True)
            return

        with open(tmp_path) as f:
            lines = f.readlines()

        new_domains = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            new_domains.append(normalize_domain(line))

        new_domains = sorted(set(new_domains))
        added = set(new_domains) - set(existing)
        removed = set(existing) - set(new_domains)

        if not added and not removed:
            click.echo("No changes.")
            return

        add_list(name, new_domains)

        if added:
            click.echo(f"  Added: {', '.join(sorted(added))}")
        if removed:
            click.echo(f"  Removed: {', '.join(sorted(removed))}")
        click.echo(f"  '{name}' now has {len(new_domains)} domain(s).")
    finally:
        os.unlink(tmp_path)


# --- App blocking ---

@cli.group("app")
def app_group():
    """Manage blocked apps (force-quit when list is active)."""
    pass


@app_group.command("add")
@click.argument("list_name")
@click.argument("apps", nargs=-1, required=True)
def app_add(list_name, apps):
    """Add apps to kill when a list is blocked.

    Use the exact app name as shown in Activity Monitor.

    Example: focus app add email WhatsApp Slack
    """
    from .store import read_config, write_config

    config = read_config()
    if list_name not in config["lists"]:
        available = ", ".join(config["lists"].keys()) or "none"
        click.echo(f"Unknown list '{list_name}'. Available: {available}", err=True)
        sys.exit(1)

    if "apps" not in config:
        config["apps"] = {}
    existing = set(config["apps"].get(list_name, []))
    new_apps = set(apps)
    config["apps"][list_name] = sorted(existing | new_apps)
    write_config(config)

    added = new_apps - existing
    if added:
        click.echo(f"Added to '{list_name}': {', '.join(sorted(added))}")
    else:
        click.echo("No new apps added (already in list).")


@app_group.command("remove")
@click.argument("list_name")
@click.argument("apps", nargs=-1, required=True)
def app_remove(list_name, apps):
    """Stop killing an app when a list is blocked.

    Example: focus app remove email WhatsApp
    """
    from .store import read_config, write_config

    config = read_config()
    if "apps" not in config or list_name not in config["apps"]:
        click.echo(f"No apps configured for '{list_name}'.", err=True)
        sys.exit(1)

    existing = set(config["apps"][list_name])
    to_remove = set(apps)
    remaining = sorted(existing - to_remove)
    removed = existing & to_remove

    if not removed:
        click.echo("Nothing to remove.")
        return

    config["apps"][list_name] = remaining
    write_config(config)
    click.echo(f"Removed from '{list_name}': {', '.join(sorted(removed))}")


@app_group.command("list")
def app_list():
    """Show which apps are killed per list."""
    from .store import read_config

    config = read_config()
    apps = config.get("apps", {})

    if not apps or all(len(v) == 0 for v in apps.values()):
        click.echo("No apps configured. Add with: focus app add <list> <AppName>")
        return

    for list_name, app_names in apps.items():
        if app_names:
            click.echo(f"  {click.style(list_name, bold=True)}: {', '.join(app_names)}")
    click.echo()


# --- Presets ---

@cli.group("preset")
def preset_group():
    """Manage presets (named combos of lists + duration)."""
    pass


@preset_group.command("add")
@click.argument("name")
@click.argument("lists", nargs=-1, required=True)
@click.option("--for", "duration", required=True, help="Default duration (e.g., 2h)")
def preset_add(name, lists, duration):
    """Create a preset that combines multiple lists with a default duration.

    Example: focus preset add deepwork social news entertainment --for 2h
    """
    from .store import add_preset, read_config

    # Validate duration
    try:
        parse_duration(duration)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    # Validate lists exist
    config = read_config()
    for l in lists:
        if l not in config["lists"]:
            available = ", ".join(config["lists"].keys()) or "none"
            click.echo(f"Unknown list '{l}'. Available: {available}", err=True)
            sys.exit(1)

    add_preset(name, list(lists), duration)
    click.echo(f"Created preset '{name}': {', '.join(lists)} for {duration}")


@preset_group.command("list")
def preset_list():
    """Show all presets."""
    from .store import get_all_presets

    presets = get_all_presets()
    if not presets:
        click.echo("No presets. Create one with: focus preset add <name> <lists...> --for 2h")
        return

    for name, p in presets.items():
        click.echo(f"  {click.style(name, bold=True)} — {', '.join(p['lists'])} for {p['duration']}")
    click.echo()


@preset_group.command("remove")
@click.argument("name")
def preset_remove(name):
    """Remove a preset."""
    from .store import remove_preset

    if remove_preset(name):
        click.echo(f"Removed preset '{name}'.")
    else:
        click.echo(f"Preset '{name}' not found.", err=True)
        sys.exit(1)


@cli.command("start")
@click.argument("preset_name")
@click.option("--for", "duration", default=None, help="Override preset duration (e.g., 3h)")
def start_cmd(preset_name, duration):
    """Start blocking using a preset.

    Example: focus start deepwork
    """
    _require_install()

    from .store import get_preset, read_config

    preset = get_preset(preset_name)
    if preset is None:
        click.echo(f"Preset '{preset_name}' not found. Run 'focus preset list'.", err=True)
        sys.exit(1)

    # Validate preset's lists still exist
    config = read_config()
    for l in preset["lists"]:
        if l not in config["lists"]:
            click.echo(f"Preset '{preset_name}' references list '{l}' which no longer exists.", err=True)
            sys.exit(1)

    dur_str = duration or preset["duration"]
    try:
        td = parse_duration(dur_str)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    # Need root
    if os.geteuid() != 0:
        args = ["start", preset_name]
        if duration:
            args += ["--for", duration]
        _sudo_run(args)

    from .blocker import activate_block

    try:
        block = activate_block(preset["lists"], td)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    end_time = datetime.fromisoformat(block.end_time)
    click.echo()
    click.echo(click.style(f"  {preset_name} activated.", fg="red", bold=True))
    click.echo(f"  Lists:   {', '.join(block.lists)}")
    click.echo(f"  Until:   {end_time.strftime('%H:%M on %b %d')}")
    click.echo(f"  Domains: {len(block.domains)} blocked")
    click.echo()
    click.echo(click.style("  This cannot be undone.", fg="yellow"))
    click.echo()


# --- Pomodoro ---

@cli.command("pomodoro")
@click.argument("preset_name", required=False)
@click.option("--lists", "list_names", multiple=True, help="Ad-hoc lists (instead of preset)")
@click.option("--sessions", default=4, help="Number of work sessions (default: 4)")
@click.option("--work", default="25m", help="Work duration (default: 25m)")
@click.option("--break", "brk", default="5m", help="Break duration (default: 5m)")
@click.option("--long-break", default="15m", help="Long break every 4th session (default: 15m)")
def pomodoro_cmd(preset_name, list_names, sessions, work, brk, long_break):
    """Start a pomodoro session with work/break cycles.

    Examples:
      focus pomodoro deepwork
      focus pomodoro deepwork --sessions 6 --work 50m --break 10m
      focus pomodoro --lists social news --sessions 4
    """
    _require_install()

    from .store import get_preset

    # Resolve lists
    if preset_name:
        preset = get_preset(preset_name)
        if preset is None:
            click.echo(f"Preset '{preset_name}' not found.", err=True)
            sys.exit(1)
        target_lists = preset["lists"]
    elif list_names:
        target_lists = list(list_names)
    else:
        click.echo("Provide a preset name or --lists. Example: focus pomodoro deepwork", err=True)
        sys.exit(1)

    if sessions < 1:
        click.echo("Sessions must be at least 1.", err=True)
        sys.exit(1)

    # Parse durations
    try:
        work_td = parse_duration(work)
        brk_td = parse_duration(brk)
        long_brk_td = parse_duration(long_break)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    # Need root
    if os.geteuid() != 0:
        args = ["pomodoro"]
        if preset_name:
            args.append(preset_name)
        for l in list_names:
            args += ["--lists", l]
        args += ["--sessions", str(sessions), "--work", work, "--break", brk, "--long-break", long_break]
        _sudo_run(args)

    from .blocker import activate_pomodoro

    try:
        blocks = activate_pomodoro(target_lists, sessions, work_td, brk_td, long_brk_td)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    last_end = datetime.fromisoformat(blocks[-1].end_time)
    total_work = format_duration(work_td * sessions)
    click.echo()
    click.echo(click.style("  Pomodoro started.", fg="red", bold=True))
    click.echo(f"  Lists:    {', '.join(target_lists)}")
    click.echo(f"  Sessions: {sessions} x {format_duration(work_td)} work")
    click.echo(f"  Breaks:   {format_duration(brk_td)} short / {format_duration(long_brk_td)} long (every 4th)")
    click.echo(f"  Done at:  {last_end.strftime('%H:%M on %b %d')}")
    click.echo()
    click.echo(click.style("  Work sessions cannot be skipped.", fg="yellow"))
    click.echo()


# --- Blocking ---

@cli.command("block")
@click.argument("lists", nargs=-1, required=True)
@click.option("--for", "duration", required=True, help="Duration (e.g., 2h, 30m, 1h30m)")
def block_cmd(lists, duration):
    """Start blocking selected lists. Cannot be undone once started.

    Example: focus block social news --for 2h
    """
    _require_install()

    try:
        td = parse_duration(duration)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    # Validate lists exist before sudo escalation
    from .store import read_config
    config = read_config()
    for name in lists:
        if name not in config["lists"]:
            available = ", ".join(config["lists"].keys()) or "none"
            click.echo(f"Unknown list '{name}'. Available: {available}", err=True)
            sys.exit(1)

    # Need root for /etc/hosts
    if os.geteuid() != 0:
        _sudo_run(["block"] + list(lists) + ["--for", duration])

    from .blocker import activate_block

    try:
        block = activate_block(lists, td)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    end_time = datetime.fromisoformat(block.end_time)
    click.echo()
    click.echo(click.style("  Block activated.", fg="red", bold=True))
    click.echo(f"  Lists:   {', '.join(block.lists)}")
    click.echo(f"  Until:   {end_time.strftime('%H:%M on %b %d')}")
    click.echo(f"  Domains: {len(block.domains)} blocked")
    click.echo()
    click.echo(click.style("  This cannot be undone.", fg="yellow"))
    click.echo()


# --- Guide ---

GUIDE = """\

  \033[1mFocus — Quick Guide\033[0m

  \033[1mBlocking:\033[0m
    focus start deepwork              Use a preset (deepwork/casual/lockdown)
    focus start deepwork --for 4h     Override preset duration
    focus block social news --for 2h  Block specific lists
    focus block whatsapp --for 1h     Block just one list
    focus status                      See what's active
    focus cancel --force              Emergency cancel all blocks

  \033[1mPomodoro:\033[0m
    focus pomodoro deepwork                  4x25m work / 5m break
    focus pomodoro deepwork --sessions 6     More sessions
    focus pomodoro casual --work 50m --break 10m  Custom timing

  \033[1mSchedules (set once, runs automatically):\033[0m
    focus schedule add social --weekdays 9:00-17:00
    focus schedule add entertainment --daily 22:00-06:00
    focus schedule add social --once "2026-05-22 14:00" --for 3h
    focus schedule list
    focus schedule remove <id> --force

  \033[1mManaging lists & apps:\033[0m
    focus lists                        View all block lists
    focus list add social snapchat.com Add a site
    focus list drop social snapchat.com Remove a site
    focus list edit social             Bulk edit in $EDITOR
    focus app list                     See blocked apps
    focus app add email Telegram       Kill app when list is blocked
    focus app remove email Telegram    Stop killing app

  \033[1mPresets:\033[0m
    focus preset add work social news --for 3h
    focus preset list
    focus preset remove work
"""


@cli.command("guide")
def guide_cmd():
    """Show usage guide with examples."""
    click.echo(GUIDE)


# --- Cancel ---

@cli.command("cancel")
@click.option("--force", is_flag=True, required=True, help="Required flag to confirm cancellation")
def cancel_cmd(force):
    """Cancel all active blocks and schedules. Requires --force.

    Example: focus cancel --force
    """
    _require_install()

    from .store import get_active_blocks, get_schedules

    active = get_active_blocks()
    from .store import get_pending_blocks
    pending = get_pending_blocks()
    schedules = get_schedules()

    if not active and not pending and not schedules:
        click.echo("Nothing to cancel.")
        return

    if os.geteuid() != 0:
        _sudo_run(["cancel", "--force"])

    from .store import write_state
    from .blocker import apply_all_blocks

    write_state({"active_blocks": [], "schedules": []})
    apply_all_blocks()

    count = len(active) + len(pending)
    click.echo()
    click.echo(click.style("  All blocks cancelled.", fg="green", bold=True))
    if count:
        click.echo(f"  Cleared {count} block(s).")
    if schedules:
        click.echo(f"  Cleared {len(schedules)} schedule(s).")
    click.echo(f"  /etc/hosts cleaned.")
    click.echo()


# --- Status ---

@cli.command("status")
def status_cmd():
    """Show active blocks and schedules."""
    from .blocker import get_status
    from .store import get_pending_blocks

    status = get_status()
    active = status["active_blocks"]
    pending = get_pending_blocks()
    schedules = status["schedules"]
    domains = status["blocked_domains"]

    if not active and not pending and not schedules:
        click.echo("No active blocks or schedules.")
        return

    if active:
        click.echo(click.style("\n  Active Blocks:", bold=True))
        for block in active:
            end = datetime.fromisoformat(block.end_time)
            remaining = end - datetime.now()
            click.echo(
                f"    [{block.id}] {', '.join(block.lists)} "
                f"— {format_duration(remaining)} remaining "
                f"(until {end.strftime('%H:%M')})"
            )

    if pending:
        click.echo(click.style("\n  Upcoming:", bold=True))
        for block in pending:
            start = datetime.fromisoformat(block.start_time)
            end = datetime.fromisoformat(block.end_time)
            click.echo(
                f"    [{block.id}] {', '.join(block.lists)} "
                f"— {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
            )

    if schedules:
        click.echo(click.style("\n  Schedules:", bold=True))
        WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for s in schedules:
            if s.schedule_type == "recurring":
                days = ", ".join(WEEKDAY_NAMES[d] for d in (s.weekdays or []))
                click.echo(
                    f"    [{s.id}] {', '.join(s.lists)} "
                    f"— {days} {s.start_time}-{s.end_time}"
                )
            elif s.schedule_type == "once":
                at = datetime.fromisoformat(s.at)
                click.echo(
                    f"    [{s.id}] {', '.join(s.lists)} "
                    f"— once at {at.strftime('%b %d %H:%M')} "
                    f"for {s.duration_minutes}m"
                )

    if domains:
        click.echo(f"\n  {len(domains)} domain(s) currently blocked.")
    click.echo()


# --- Scheduling ---

@cli.group("schedule")
def schedule_group():
    """Manage scheduled blocks."""
    pass


@schedule_group.command("add")
@click.argument("lists", nargs=-1, required=True)
@click.option("--weekdays", help="Recurring weekday block (e.g., 9:00-17:00)")
@click.option("--weekends", help="Recurring weekend block (e.g., 10:00-14:00)")
@click.option("--daily", help="Recurring daily block (e.g., 22:00-06:00)")
@click.option("--once", help="One-time block datetime (e.g., '2026-05-20 14:00')")
@click.option("--for", "duration", help="Duration for one-time blocks (e.g., 2h)")
def schedule_add(lists, weekdays, weekends, daily, once, duration):
    """Add a scheduled block.

    Examples:
      focus schedule add social --weekdays 9:00-17:00
      focus schedule add news --weekends 10:00-14:00
      focus schedule add entertainment --daily 22:00-06:00
      focus schedule add social news --once "2026-05-20 14:00" --for 3h
    """
    _require_install()

    from .store import add_schedule, read_config

    # Validate lists exist
    config = read_config()
    for name in lists:
        if name not in config["lists"]:
            available = ", ".join(config["lists"].keys()) or "none"
            click.echo(f"Unknown list '{name}'. Available: {available}", err=True)
            sys.exit(1)

    # Determine schedule type
    option_count = sum(1 for x in [weekdays, weekends, daily, once] if x)
    if option_count == 0:
        click.echo("Specify one of: --weekdays, --weekends, --daily, --once", err=True)
        sys.exit(1)
    if option_count > 1:
        click.echo("Use only one of: --weekdays, --weekends, --daily, --once", err=True)
        sys.exit(1)

    # Validate all inputs before sudo escalation
    if once:
        if not duration:
            click.echo("--for is required with --once", err=True)
            sys.exit(1)
        try:
            parse_duration(duration)
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)
        try:
            datetime.fromisoformat(once)
        except ValueError:
            click.echo(f"Invalid datetime '{once}'. Use format: 2026-05-20 14:00", err=True)
            sys.exit(1)
    else:
        time_range = weekdays or weekends or daily
        try:
            parse_time_range(time_range)
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)

    # Need root to write state
    if os.geteuid() != 0:
        args = ["schedule", "add"] + list(lists)
        if weekdays:
            args += ["--weekdays", weekdays]
        if weekends:
            args += ["--weekends", weekends]
        if daily:
            args += ["--daily", daily]
        if once:
            args += ["--once", once]
        if duration:
            args += ["--for", duration]
        _sudo_run(args)

    schedule_id = generate_id()

    if once:
        # One-time schedule (already validated above)
        td = parse_duration(duration)
        at = datetime.fromisoformat(once)

        schedule = Schedule(
            id=schedule_id,
            lists=list(lists),
            schedule_type="once",
            at=at.isoformat(timespec="seconds"),
            duration_minutes=int(td.total_seconds() // 60),
        )
        add_schedule(schedule)
        click.echo(
            f"Scheduled one-time block: {', '.join(lists)} "
            f"at {at.strftime('%b %d %H:%M')} for {format_duration(td)}"
        )
    else:
        # Recurring schedule
        if weekdays:
            time_range = weekdays
            day_indices = [0, 1, 2, 3, 4]  # Mon-Fri
            day_label = "weekdays"
        elif weekends:
            time_range = weekends
            day_indices = [5, 6]  # Sat-Sun
            day_label = "weekends"
        else:  # daily
            time_range = daily
            day_indices = [0, 1, 2, 3, 4, 5, 6]
            day_label = "daily"

        try:
            start, end = parse_time_range(time_range)
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)

        schedule = Schedule(
            id=schedule_id,
            lists=list(lists),
            schedule_type="recurring",
            weekdays=day_indices,
            start_time=start,
            end_time=end,
        )
        add_schedule(schedule)
        click.echo(
            f"Scheduled recurring block: {', '.join(lists)} "
            f"{day_label} {start}-{end}"
        )


@schedule_group.command("list")
def schedule_list():
    """Show all scheduled blocks."""
    from .store import get_schedules
    from .scheduler import is_schedule_active_now

    schedules = get_schedules()
    if not schedules:
        click.echo("No schedules. Create one with: focus schedule add <lists> --weekdays 9:00-17:00")
        return

    WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    now = datetime.now()

    for s in schedules:
        active = is_schedule_active_now(s, now)
        status = click.style(" ACTIVE", fg="red", bold=True) if active else ""

        if s.schedule_type == "recurring":
            days = ", ".join(WEEKDAY_NAMES[d] for d in (s.weekdays or []))
            click.echo(
                f"  [{s.id}] {', '.join(s.lists)} — {days} {s.start_time}-{s.end_time}{status}"
            )
        elif s.schedule_type == "once":
            at = datetime.fromisoformat(s.at)
            click.echo(
                f"  [{s.id}] {', '.join(s.lists)} — once at {at.strftime('%b %d %H:%M')} "
                f"for {s.duration_minutes}m{status}"
            )
    click.echo()


@schedule_group.command("remove")
@click.argument("schedule_id")
@click.option("--force", is_flag=True, help="Remove even if currently active")
def schedule_remove(schedule_id, force):
    """Remove a scheduled block by ID."""
    from .store import get_schedules, remove_schedule
    from .scheduler import is_schedule_active_now

    # Find the schedule
    schedules = get_schedules()
    target = None
    for s in schedules:
        if s.id == schedule_id:
            target = s
            break

    if target is None:
        click.echo(f"Schedule '{schedule_id}' not found.", err=True)
        sys.exit(1)

    if is_schedule_active_now(target) and not force:
        click.echo(
            f"Schedule '{schedule_id}' is currently active. "
            f"Use --force to remove anyway.",
            err=True,
        )
        sys.exit(1)

    # Need root to write state
    if os.geteuid() != 0:
        args = ["schedule", "remove", schedule_id]
        if force:
            args.append("--force")
        _sudo_run(args)

    remove_schedule(schedule_id)
    click.echo(f"Removed schedule '{schedule_id}'.")

    if force:
        from .blocker import apply_all_blocks
        apply_all_blocks()
        click.echo("Updated /etc/hosts.")


# --- Install/Uninstall ---

@cli.command("install")
def install_cmd():
    """Install the focus daemon (requires sudo)."""
    if os.geteuid() != 0:
        _sudo_run(["install"])

    from .daemon import install_daemon
    install_daemon()


@cli.command("uninstall")
def uninstall_cmd():
    """Uninstall the focus daemon (requires sudo)."""
    if os.geteuid() != 0:
        _sudo_run(["uninstall"])

    from .blocker import has_active_blocks
    if has_active_blocks():
        click.echo("Cannot uninstall: there are active blocks.", err=True)
        sys.exit(1)

    from .daemon import uninstall_daemon
    uninstall_daemon()


def main():
    cli()
