#!/usr/bin/env python3
"""
Focus Daemon — standalone enforcement script run by launchd as root.

This script uses ONLY stdlib modules (no third-party deps) because it runs
via /usr/bin/python3 (system Python, SIP-protected).

It enforces site blocks by:
1. Reading state.json to determine what should be blocked
2. Evaluating recurring/one-time schedules
3. Writing the correct entries to /etc/hosts
4. Removing expired blocks
5. Flushing DNS cache
"""

import json
import fcntl
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# --- Constants (must match focus/config.py) ---
STATE_DIR = Path("/usr/local/etc/focus")
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / ".state.lock"
HOSTS_LOCK = STATE_DIR / ".hosts.lock"
HOSTS_PATH = Path("/etc/hosts")

# Config path is passed as argv[1] during install, defaults to detecting user
def _get_config_file():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    # Fallback: find the first real user's home directory
    for user_dir in Path("/Users").iterdir():
        cfg = user_dir / ".focus" / "config.json"
        if cfg.exists():
            return cfg
    return STATE_DIR / "config.json"

CONFIG_FILE = _get_config_file()
MARKER_START = "# === FOCUS BLOCK START (DO NOT EDIT) ==="
MARKER_END = "# === FOCUS BLOCK END ==="


def log(msg):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


# --- File I/O with locking ---

def read_json_locked(path):
    """Read a JSON file with exclusive lock."""
    if not path.exists():
        return {}
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        data = json.loads(path.read_text())
        return data
    except (json.JSONDecodeError, IOError) as e:
        log(f"Warning: could not read {path}: {e}")
        return {}
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def write_json_locked(path, data):
    """Write a JSON file with exclusive lock (atomic)."""
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        content = json.dumps(data, indent=2) + "\n"
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(content)
        tmp.rename(path)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


# --- Domain expansion ---

def expand_domain(domain):
    """Expand domain to include www. variant."""
    domain = domain.strip().lower().rstrip(".")
    domains = [domain]
    if not domain.startswith("www."):
        domains.append(f"www.{domain}")
    return domains


# --- Schedule evaluation ---

def is_schedule_active(schedule, now):
    """Check if a schedule is currently active."""
    stype = schedule.get("schedule_type")

    if stype == "recurring":
        weekday = now.weekday()
        weekdays = schedule.get("weekdays", [])
        if weekdays and weekday not in weekdays:
            return False
        start = schedule.get("start_time", "")
        end = schedule.get("end_time", "")
        if start and end:
            current = now.strftime("%H:%M")
            if start <= end:
                return start <= current < end
            else:
                # Overnight range like 22:00-06:00
                return current >= start or current < end
        return False

    elif stype == "once":
        at_str = schedule.get("at")
        dur = schedule.get("duration_minutes", 0)
        if not at_str or not dur:
            return False
        at = datetime.fromisoformat(at_str)
        end = at + timedelta(minutes=dur)
        return at <= now < end

    return False


def is_once_schedule_expired(schedule, now):
    """Check if a one-time schedule has fully elapsed."""
    if schedule.get("schedule_type") != "once":
        return False
    at_str = schedule.get("at")
    dur = schedule.get("duration_minutes", 0)
    if not at_str or not dur:
        return True
    at = datetime.fromisoformat(at_str)
    end = at + timedelta(minutes=dur)
    return now >= end


# --- /etc/hosts management ---

def read_hosts():
    """Read /etc/hosts and split into (pre, focus, post)."""
    content = HOSTS_PATH.read_text()
    start_idx = content.find(MARKER_START)
    end_idx = content.find(MARKER_END)

    if start_idx == -1 or end_idx == -1:
        return content.rstrip("\n"), "", ""

    pre = content[:start_idx].rstrip("\n")
    post = content[end_idx + len(MARKER_END):].strip("\n")
    return pre, "", post


def generate_hosts_section(domains):
    """Generate the focus section for /etc/hosts."""
    if not domains:
        return ""
    lines = [MARKER_START]
    for domain in sorted(set(domains)):
        lines.append(f"127.0.0.1\t{domain}")
        lines.append(f"::1\t\t{domain}")
    lines.append(MARKER_END)
    return "\n".join(lines)


def write_hosts(domains):
    """Write blocked domains to /etc/hosts. Locked to prevent races with CLI."""
    lock_fd = open(HOSTS_LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        pre, _, post = read_hosts()
        section = generate_hosts_section(domains)

        parts = [pre]
        if section:
            parts.append(section)
        if post:
            parts.append(post)

        new_content = "\n\n".join(parts) + "\n"

        tmp_path = HOSTS_PATH.parent / "hosts.focus.tmp"
        tmp_path.write_text(new_content)
        tmp_path.rename(HOSTS_PATH)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def flush_dns():
    """Flush macOS DNS cache."""
    subprocess.run(["dscacheutil", "-flushcache"], capture_output=True)
    subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True)


# --- Main enforcement logic ---

def enforce():
    """Main enforcement: compute what should be blocked, apply it."""
    now = datetime.now()

    config = read_json_locked(CONFIG_FILE)
    state = read_json_locked(STATE_FILE)

    lists_config = config.get("lists", {})
    active_blocks = state.get("active_blocks", [])
    schedules = state.get("schedules", [])

    # Collect all domains that should be blocked right now
    blocked_domains = set()
    blocked_lists = set()

    # From active blocks (started and not expired)
    remaining_blocks = []
    for block in active_blocks:
        start_time = datetime.fromisoformat(block["start_time"])
        end_time = datetime.fromisoformat(block["end_time"])
        if now < end_time:
            remaining_blocks.append(block)
            if start_time <= now:
                # Block is currently active — enforce its domains
                blocked_domains.update(block.get("domains", []))
                blocked_lists.update(block.get("lists", []))
            # else: future block (pomodoro), keep but don't enforce yet
        else:
            log(f"Block {block['id']} expired, removing.")

    # From active schedules
    remaining_schedules = []
    for schedule in schedules:
        if is_schedule_active(schedule, now):
            for list_name in schedule.get("lists", []):
                blocked_lists.add(list_name)
                for domain in lists_config.get(list_name, []):
                    blocked_domains.update(expand_domain(domain))

        # Clean up expired one-time schedules
        if is_once_schedule_expired(schedule, now):
            log(f"One-time schedule {schedule['id']} expired, removing.")
        else:
            remaining_schedules.append(schedule)

    # Update state if anything changed
    if (len(remaining_blocks) != len(active_blocks) or
            len(remaining_schedules) != len(schedules)):
        state["active_blocks"] = remaining_blocks
        state["schedules"] = remaining_schedules
        write_json_locked(STATE_FILE, state)

    # Apply to /etc/hosts
    write_hosts(sorted(blocked_domains))
    flush_dns()

    # Kill blocked apps
    apps_config = config.get("apps", {})
    killed = []
    for list_name in blocked_lists:
        for app_name in apps_config.get(list_name, []):
            result = subprocess.run(
                ["killall", app_name],
                capture_output=True,
            )
            if result.returncode == 0:
                killed.append(app_name)

    # Only log when something interesting happens (not every 15s idle tick)
    state_changed = (len(remaining_blocks) != len(active_blocks) or
                     len(remaining_schedules) != len(schedules))
    if state_changed or blocked_domains or killed:
        parts = [f"Enforced {len(blocked_domains)} domain(s)."]
        if killed:
            parts.append(f"Killed: {', '.join(killed)}")
        log(" ".join(parts))


def truncate_log():
    """Truncate log file if it exceeds 1MB."""
    log_path = Path("/usr/local/var/log/focus.log")
    try:
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            lines = log_path.read_text().splitlines()
            # Keep last 1000 lines
            log_path.write_text("\n".join(lines[-1000:]) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    try:
        truncate_log()
        enforce()
    except Exception as e:
        log(f"Error: {e}")
        sys.exit(1)
