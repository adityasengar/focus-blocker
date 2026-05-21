import os
import shutil
import subprocess
import plistlib
from pathlib import Path

import click

from .config import (
    DAEMON_LABEL, DAEMON_PLIST_PATH, DAEMON_SCRIPT_DIR, DAEMON_SCRIPT_PATH,
    DAEMON_LOG_PATH, DAEMON_ERR_PATH, HOSTS_PATH, STATE_DIR, CONFIG_DIR,
    CONFIG_FILE, STATE_FILE, SYSTEM_PYTHON, LOG_DIR,
)


def _get_daemon_source() -> Path:
    """Get path to the daemon source script."""
    return Path(__file__).parent.parent / "daemon" / "focus_daemon.py"


def _generate_plist() -> dict:
    """Generate the LaunchDaemon plist dictionary."""
    return {
        "Label": DAEMON_LABEL,
        "ProgramArguments": [
            SYSTEM_PYTHON,
            str(DAEMON_SCRIPT_PATH),
            str(CONFIG_FILE),
        ],
        "StartInterval": 15,
        "RunAtLoad": True,
        "StandardOutPath": str(DAEMON_LOG_PATH),
        "StandardErrorPath": str(DAEMON_ERR_PATH),
        "WatchPaths": [str(HOSTS_PATH), str(STATE_FILE)],
    }


def install_daemon():
    """Install or update the focus LaunchDaemon."""
    reinstall = DAEMON_PLIST_PATH.exists()
    if reinstall:
        click.echo("Updating existing installation...")
    click.echo("[1/5] Creating directories...")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o755)
    os.chown(STATE_DIR, 0, 0)  # root:wheel

    # Create user config dir (owned by the real user, not root)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    real_uid = int(os.environ.get("SUDO_UID", os.getuid()))
    real_gid = int(os.environ.get("SUDO_GID", os.getgid()))
    os.chown(CONFIG_DIR, real_uid, real_gid)

    # Create state.json if it doesn't exist (root-only write)
    if not STATE_FILE.exists():
        STATE_FILE.write_text('{"active_blocks": [], "schedules": []}\n')
    os.chmod(STATE_FILE, 0o644)
    os.chown(STATE_FILE, 0, 0)

    click.echo("[2/5] Installing daemon script...")
    DAEMON_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    source = _get_daemon_source()
    if not source.exists():
        click.echo(f"Error: daemon source not found at {source}", err=True)
        raise SystemExit(1)
    shutil.copy2(source, DAEMON_SCRIPT_PATH)
    os.chmod(DAEMON_SCRIPT_PATH, 0o755)

    click.echo("[3/5] Installing LaunchDaemon plist...")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    plist_data = _generate_plist()
    with open(DAEMON_PLIST_PATH, "wb") as f:
        plistlib.dump(plist_data, f)
    os.chmod(DAEMON_PLIST_PATH, 0o644)
    os.chown(DAEMON_PLIST_PATH, 0, 0)

    click.echo("[4/5] Loading daemon...")
    # Unload first if already loaded (ignore errors)
    subprocess.run(
        ["launchctl", "bootout", f"system/{DAEMON_LABEL}"],
        capture_output=True,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", "system", str(DAEMON_PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"Warning: launchctl bootstrap returned: {result.stderr.strip()}")

    click.echo("[5/5] Verifying daemon...")
    result = subprocess.run(
        ["launchctl", "print", f"system/{DAEMON_LABEL}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        click.echo()
        click.echo(click.style("  Focus daemon installed successfully.", fg="green", bold=True))
        click.echo("  Run 'focus list add <name> <domains>' to create your first block list.")
        click.echo()
    else:
        click.echo(click.style("  Warning: daemon may not be running.", fg="yellow"))
        click.echo(f"  Check logs: {DAEMON_LOG_PATH}")
        click.echo()


def uninstall_daemon():
    """Uninstall the focus LaunchDaemon."""
    click.echo("Uninstalling focus daemon...")

    # Unload
    subprocess.run(
        ["launchctl", "bootout", f"system/{DAEMON_LABEL}"],
        capture_output=True,
    )

    # Remove files
    for path in [DAEMON_PLIST_PATH, DAEMON_SCRIPT_PATH]:
        if path.exists():
            path.unlink()
            click.echo(f"  Removed {path}")

    if DAEMON_SCRIPT_DIR.exists() and not any(DAEMON_SCRIPT_DIR.iterdir()):
        DAEMON_SCRIPT_DIR.rmdir()

    click.echo()
    click.echo(click.style("  Focus daemon uninstalled.", fg="green", bold=True))
    click.echo("  Config and state files preserved in /usr/local/etc/focus/")
    click.echo()


def is_daemon_installed() -> bool:
    """Check if the daemon plist is installed."""
    return DAEMON_PLIST_PATH.exists()
