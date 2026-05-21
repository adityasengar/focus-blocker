import fcntl
import subprocess
from pathlib import Path
from typing import List, Tuple

from .config import HOSTS_PATH, MARKER_START, MARKER_END, STATE_DIR

HOSTS_LOCK = STATE_DIR / ".hosts.lock"


def read_hosts() -> Tuple[str, str, str]:
    """Read /etc/hosts and split into (before_markers, focus_section, after_markers)."""
    content = HOSTS_PATH.read_text()

    start_idx = content.find(MARKER_START)
    end_idx = content.find(MARKER_END)

    if start_idx == -1 or end_idx == -1:
        # No existing focus section
        return content.rstrip("\n"), "", ""

    pre = content[:start_idx].rstrip("\n")
    focus = content[start_idx:end_idx + len(MARKER_END)]
    post = content[end_idx + len(MARKER_END):].strip("\n")
    return pre, focus, post


def generate_focus_section(domains: List[str]) -> str:
    """Generate the focus block section for /etc/hosts."""
    if not domains:
        return ""

    lines = [MARKER_START]
    for domain in sorted(set(domains)):
        lines.append(f"127.0.0.1\t{domain}")
        lines.append(f"::1\t\t{domain}")
    lines.append(MARKER_END)
    return "\n".join(lines)


def apply_blocks(domains: List[str]):
    """Write blocked domains to /etc/hosts and flush DNS. Locked to prevent races."""
    lock_fd = None
    try:
        if HOSTS_LOCK.parent.exists():
            lock_fd = open(HOSTS_LOCK, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

        pre, _, post = read_hosts()
        focus_section = generate_focus_section(domains)

        parts = [pre]
        if focus_section:
            parts.append(focus_section)
        if post:
            parts.append(post)

        new_content = "\n\n".join(parts) + "\n"

        tmp_path = HOSTS_PATH.parent / "hosts.focus.tmp"
        tmp_path.write_text(new_content)
        tmp_path.rename(HOSTS_PATH)
    finally:
        if lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    flush_dns()


def clear_blocks():
    """Remove all focus entries from /etc/hosts."""
    apply_blocks([])


def flush_dns():
    """Flush macOS DNS cache."""
    subprocess.run(
        ["dscacheutil", "-flushcache"],
        capture_output=True,
    )
    subprocess.run(
        ["killall", "-HUP", "mDNSResponder"],
        capture_output=True,
    )


def get_currently_blocked_domains() -> List[str]:
    """Read /etc/hosts and return list of domains currently blocked by focus."""
    _, focus_section, _ = read_hosts()
    if not focus_section:
        return []

    domains = []
    for line in focus_section.split("\n"):
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("127.0.0.1", "::1"):
            domain = parts[1]
            if domain not in domains:
                domains.append(domain)
    return domains
