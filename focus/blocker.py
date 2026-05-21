from datetime import datetime, timedelta
from typing import List

from .models import ActiveBlock
from .store import (
    read_config, add_active_block, get_active_blocks,
    remove_expired_blocks,
)
from .hosts import apply_blocks
from .utils import expand_domain, generate_id
from .scheduler import get_scheduled_domains


def activate_block(list_names: List[str], duration: timedelta) -> ActiveBlock:
    """Activate a block for the given lists and duration."""
    config = read_config()
    available = list(config["lists"].keys())

    # Validate lists exist
    for name in list_names:
        if name not in config["lists"]:
            raise ValueError(
                f"Unknown list '{name}'. Available: {', '.join(available) or 'none'}"
            )

    # Resolve and expand domains
    all_domains = []
    for name in list_names:
        for domain in config["lists"][name]:
            all_domains.extend(expand_domain(domain))

    now = datetime.now()
    block = ActiveBlock(
        id=generate_id(),
        lists=list(list_names),
        domains=sorted(set(all_domains)),
        start_time=now.isoformat(timespec="seconds"),
        end_time=(now + duration).isoformat(timespec="seconds"),
    )

    add_active_block(block)

    # Apply all active domains to /etc/hosts
    apply_all_blocks()

    return block


def activate_pomodoro(
    list_names: List[str],
    sessions: int,
    work: timedelta,
    brk: timedelta,
    long_brk: timedelta,
) -> List[ActiveBlock]:
    """Create multiple sequential work blocks with breaks in between."""
    config = read_config()
    available = list(config["lists"].keys())

    for name in list_names:
        if name not in config["lists"]:
            raise ValueError(
                f"Unknown list '{name}'. Available: {', '.join(available) or 'none'}"
            )

    all_domains = []
    for name in list_names:
        for domain in config["lists"][name]:
            all_domains.extend(expand_domain(domain))
    all_domains = sorted(set(all_domains))

    blocks = []
    cursor = datetime.now()

    for i in range(sessions):
        block = ActiveBlock(
            id=generate_id(),
            lists=list(list_names),
            domains=all_domains,
            start_time=cursor.isoformat(timespec="seconds"),
            end_time=(cursor + work).isoformat(timespec="seconds"),
        )
        add_active_block(block)
        blocks.append(block)

        cursor += work
        # Add break after each session (except the last)
        if i < sessions - 1:
            if (i + 1) % 4 == 0:
                cursor += long_brk
            else:
                cursor += brk

    apply_all_blocks()
    return blocks


def deactivate_expired():
    """Remove expired blocks and update /etc/hosts."""
    expired = remove_expired_blocks()
    if expired:
        apply_all_blocks()
    return expired


def apply_all_blocks():
    """Compute all domains that should be blocked and apply to /etc/hosts."""
    all_domains = get_all_blocked_domains()
    apply_blocks(all_domains)


def get_all_blocked_domains() -> List[str]:
    """Get union of all domains from active blocks and active schedules."""
    domains = set()

    # From active blocks
    for block in get_active_blocks():
        domains.update(block.domains)

    # From active schedules
    domains.update(get_scheduled_domains())

    return sorted(domains)


def get_status() -> dict:
    """Get current blocking status."""
    active = get_active_blocks()
    from .store import get_schedules
    schedules = get_schedules()

    return {
        "active_blocks": active,
        "schedules": schedules,
        "blocked_domains": get_all_blocked_domains(),
    }


def has_active_blocks() -> bool:
    """Check if there are any active (non-expired) blocks."""
    return len(get_active_blocks()) > 0


def is_list_active(list_name: str) -> bool:
    """Check if a list is currently in an active block."""
    for block in get_active_blocks():
        if list_name in block.lists:
            return True
    return False
