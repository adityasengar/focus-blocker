from datetime import datetime, timedelta
from typing import List

from .models import Schedule
from .store import get_schedules, read_config
from .utils import expand_domain


def is_schedule_active_now(schedule: Schedule, now: datetime = None) -> bool:
    """Check if a schedule is currently in its active window."""
    if now is None:
        now = datetime.now()

    if schedule.schedule_type == "recurring":
        weekday = now.weekday()  # 0=Monday..6=Sunday
        if schedule.weekdays is not None and weekday not in schedule.weekdays:
            return False
        if schedule.start_time and schedule.end_time:
            current_time = now.strftime("%H:%M")
            start = schedule.start_time
            end = schedule.end_time
            # Handle overnight ranges like 22:00-06:00
            if start <= end:
                return start <= current_time < end
            else:
                return current_time >= start or current_time < end
        return False

    elif schedule.schedule_type == "once":
        if not schedule.at or not schedule.duration_minutes:
            return False
        at = datetime.fromisoformat(schedule.at)
        end = at + timedelta(minutes=schedule.duration_minutes)
        return at <= now < end

    return False


def get_scheduled_domains(now: datetime = None) -> List[str]:
    """Get all domains that should be blocked right now based on schedules."""
    if now is None:
        now = datetime.now()

    config = read_config()
    domains = set()

    for schedule in get_schedules():
        if is_schedule_active_now(schedule, now):
            for list_name in schedule.lists:
                list_domains = config["lists"].get(list_name, [])
                for domain in list_domains:
                    domains.update(expand_domain(domain))

    return sorted(domains)
