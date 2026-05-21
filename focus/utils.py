import re
import hashlib
import time
from datetime import timedelta
from typing import List

DURATION_PATTERN = re.compile(
    r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m)?$", re.IGNORECASE
)


def parse_duration(s: str) -> timedelta:
    """Parse duration string like '2h', '30m', '1h30m', '1.5h'."""
    match = DURATION_PATTERN.match(s.strip())
    if not match or not any(match.groups()):
        raise ValueError(
            f"Invalid duration '{s}'. Use format like '2h', '30m', '1h30m'."
        )
    hours = float(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    td = timedelta(hours=hours, minutes=minutes)
    if td.total_seconds() <= 0:
        raise ValueError("Duration must be greater than zero.")
    return td


def normalize_domain(domain: str) -> str:
    """Lowercase and strip whitespace/trailing dots from a domain."""
    return domain.strip().lower().rstrip(".")


def expand_domain(domain: str) -> List[str]:
    """Expand a domain to include www. variant."""
    domain = normalize_domain(domain)
    domains = [domain]
    if not domain.startswith("www."):
        domains.append(f"www.{domain}")
    return domains


def generate_id() -> str:
    """Generate a short unique ID."""
    return hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:8]


def parse_time_range(s: str) -> tuple:
    """Parse a time range like '9:00-17:00' into (start, end) strings."""
    match = re.match(r"^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$", s.strip())
    if not match:
        raise ValueError(
            f"Invalid time range '{s}'. Use format like '9:00-17:00'."
        )
    start, end = match.group(1), match.group(2)
    # Normalize to HH:MM
    start = _normalize_time(start)
    end = _normalize_time(end)
    return start, end


def _normalize_time(t: str) -> str:
    """Normalize time string to HH:MM format."""
    parts = t.split(":")
    return f"{int(parts[0]):02d}:{parts[1]}"


def format_duration(td: timedelta) -> str:
    """Format a timedelta as a human-readable string."""
    total_minutes = int(td.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h{minutes}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{minutes}m"
