from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class ActiveBlock:
    id: str
    lists: List[str]
    domains: List[str]
    start_time: str  # ISO format
    end_time: str  # ISO format

    def is_expired(self) -> bool:
        return datetime.now() >= datetime.fromisoformat(self.end_time)

    def is_active_now(self) -> bool:
        now = datetime.now()
        return (datetime.fromisoformat(self.start_time) <= now
                < datetime.fromisoformat(self.end_time))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActiveBlock":
        return cls(**d)


@dataclass
class Schedule:
    id: str
    lists: List[str]
    schedule_type: str  # "recurring" or "once"
    # Recurring fields
    weekdays: Optional[List[int]] = None  # 0=Monday..6=Sunday
    start_time: Optional[str] = None  # "HH:MM"
    end_time: Optional[str] = None  # "HH:MM"
    # One-time fields
    at: Optional[str] = None  # ISO datetime
    duration_minutes: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove None fields for cleaner JSON
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Schedule":
        return cls(
            id=d["id"],
            lists=d["lists"],
            schedule_type=d["schedule_type"],
            weekdays=d.get("weekdays"),
            start_time=d.get("start_time"),
            end_time=d.get("end_time"),
            at=d.get("at"),
            duration_minutes=d.get("duration_minutes"),
        )
