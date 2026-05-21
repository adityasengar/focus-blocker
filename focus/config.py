from pathlib import Path

# User config (no sudo needed)
CONFIG_DIR = Path.home() / ".focus"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Root-owned state (daemon + sudo writes)
STATE_DIR = Path("/usr/local/etc/focus")
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / ".state.lock"
LOG_DIR = Path("/usr/local/var/log")

# /etc/hosts
HOSTS_PATH = Path("/etc/hosts")
MARKER_START = "# === FOCUS BLOCK START (DO NOT EDIT) ==="
MARKER_END = "# === FOCUS BLOCK END ==="

# LaunchDaemon
DAEMON_LABEL = "com.focus.blocker"
DAEMON_PLIST_PATH = Path(f"/Library/LaunchDaemons/{DAEMON_LABEL}.plist")
DAEMON_SCRIPT_DIR = Path("/usr/local/libexec/focus")
DAEMON_SCRIPT_PATH = DAEMON_SCRIPT_DIR / "focus_daemon.py"
DAEMON_LOG_PATH = LOG_DIR / "focus.log"
DAEMON_ERR_PATH = LOG_DIR / "focus.err"

# System Python (SIP-protected, used by daemon)
SYSTEM_PYTHON = "/usr/bin/python3"
