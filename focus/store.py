import json
import fcntl
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import CONFIG_DIR, CONFIG_FILE, STATE_FILE, LOCK_FILE, STATE_DIR
from .models import ActiveBlock, Schedule


def _ensure_dir():
    """Ensure state directory exists (called during install with sudo)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        bak = path.with_suffix(path.suffix + ".corrupt")
        print(
            f"Error: {path} contains invalid JSON.\n"
            f"  A copy has been saved to {bak}\n"
            f"  Fix the file or delete it to start fresh.",
            file=sys.stderr,
        )
        # Save corrupt file for debugging
        if not bak.exists():
            path.rename(bak)
        return {}


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2) + "\n"
    # Atomic write: write to .tmp, then rename
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Keep backup of previous version
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            bak.write_text(path.read_text())
        except OSError:
            pass  # Best-effort backup
    tmp.write_text(content)
    tmp.rename(path)


def _with_lock(func):
    """Decorator to acquire file lock for state operations."""
    def wrapper(*args, **kwargs):
        if not STATE_DIR.exists():
            # State dir not created yet (pre-install) — run without lock
            return func(*args, **kwargs)
        try:
            lock_fd = open(LOCK_FILE, "w")
        except PermissionError:
            # Non-root user reading state — skip locking (read-only is safe)
            return func(*args, **kwargs)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return func(*args, **kwargs)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
    return wrapper


# --- Config (block lists) ---

def read_config() -> dict:
    """Read block list config. Returns {"lists": {...}, "presets": {...}}."""
    data = _read_json(CONFIG_FILE)
    if "lists" not in data:
        data["lists"] = {}
    if "presets" not in data:
        data["presets"] = {}
    return data


def write_config(data: dict):
    """Write block list config."""
    _write_json(CONFIG_FILE, data)


def get_list(name: str) -> Optional[List[str]]:
    """Get domains for a named block list."""
    config = read_config()
    return config["lists"].get(name)


def add_list(name: str, domains: List[str]):
    """Add or update a block list."""
    config = read_config()
    config["lists"][name] = domains
    write_config(config)


def remove_list(name: str) -> bool:
    """Remove a block list. Returns False if not found."""
    config = read_config()
    if name not in config["lists"]:
        return False
    del config["lists"][name]
    write_config(config)
    return True


# --- Presets ---

def get_preset(name: str) -> Optional[dict]:
    """Get a preset by name. Returns {"lists": [...], "duration": "2h"} or None."""
    config = read_config()
    return config["presets"].get(name)


def add_preset(name: str, lists: List[str], duration: str):
    """Add or update a preset."""
    config = read_config()
    config["presets"][name] = {"lists": lists, "duration": duration}
    write_config(config)


def remove_preset(name: str) -> bool:
    """Remove a preset. Returns False if not found."""
    config = read_config()
    if name not in config["presets"]:
        return False
    del config["presets"][name]
    write_config(config)
    return True


def get_all_presets() -> dict:
    """Get all presets."""
    config = read_config()
    return config["presets"]


# --- State (active blocks + schedules) ---

@_with_lock
def read_state() -> dict:
    """Read state file. Returns {"active_blocks": [...], "schedules": [...]}."""
    data = _read_json(STATE_FILE)
    if "active_blocks" not in data:
        data["active_blocks"] = []
    if "schedules" not in data:
        data["schedules"] = []
    return data


@_with_lock
def write_state(data: dict):
    """Write state file."""
    _write_json(STATE_FILE, data)


@_with_lock
def add_active_block(block: ActiveBlock):
    """Add an active block to state."""
    data = _read_json(STATE_FILE) if STATE_FILE.exists() else {}
    if "active_blocks" not in data:
        data["active_blocks"] = []
    if "schedules" not in data:
        data["schedules"] = []
    data["active_blocks"].append(block.to_dict())
    _write_json(STATE_FILE, data)


@_with_lock
def remove_expired_blocks() -> List[ActiveBlock]:
    """Remove expired blocks from state. Returns removed blocks."""
    data = _read_json(STATE_FILE) if STATE_FILE.exists() else {}
    blocks = [ActiveBlock.from_dict(b) for b in data.get("active_blocks", [])]
    expired = [b for b in blocks if b.is_expired()]
    active = [b for b in blocks if not b.is_expired()]
    data["active_blocks"] = [b.to_dict() for b in active]
    _write_json(STATE_FILE, data)
    return expired


@_with_lock
def add_schedule(schedule: Schedule):
    """Add a schedule to state."""
    data = _read_json(STATE_FILE) if STATE_FILE.exists() else {}
    if "active_blocks" not in data:
        data["active_blocks"] = []
    if "schedules" not in data:
        data["schedules"] = []
    data["schedules"].append(schedule.to_dict())
    _write_json(STATE_FILE, data)


@_with_lock
def remove_schedule(schedule_id: str) -> bool:
    """Remove a schedule by ID. Returns False if not found."""
    data = _read_json(STATE_FILE) if STATE_FILE.exists() else {}
    schedules = data.get("schedules", [])
    new_schedules = [s for s in schedules if s["id"] != schedule_id]
    if len(new_schedules) == len(schedules):
        return False
    data["schedules"] = new_schedules
    _write_json(STATE_FILE, data)
    return True


def get_active_blocks() -> List[ActiveBlock]:
    """Get all currently active blocks (started and not expired)."""
    state = read_state()
    return [ActiveBlock.from_dict(b) for b in state["active_blocks"] if ActiveBlock.from_dict(b).is_active_now()]


def get_pending_blocks() -> List[ActiveBlock]:
    """Get blocks that haven't started yet (future pomodoro sessions)."""
    state = read_state()
    now = datetime.now()
    return [
        ActiveBlock.from_dict(b) for b in state["active_blocks"]
        if datetime.fromisoformat(b["start_time"]) > now
    ]


def get_schedules() -> List[Schedule]:
    """Get all schedules."""
    state = read_state()
    return [Schedule.from_dict(s) for s in state["schedules"]]
