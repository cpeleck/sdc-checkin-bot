from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class UserError(Exception):
    """An actionable error safe to show to a Discord user."""


class PermissionDenied(UserError):
    pass


class Conflict(UserError):
    pass


class Status(StrEnum):
    ON_TRACK = "On track"
    AT_RISK = "At risk"
    BLOCKED = "Blocked"


@dataclass(frozen=True)
class Actor:
    guild_id: int
    user_id: int
    role_ids: frozenset[int] = field(default_factory=frozenset)
    manage_guild: bool = False
    channel_id: int | None = None


@dataclass(frozen=True)
class CheckinInput:
    status: Status
    progress: str
    next_steps: str
    blockers: str = ""
    assistance: str = ""

    def validated(self) -> "CheckinInput":
        try:
            status = Status(self.status)
        except ValueError as exc:
            raise UserError("Choose On track, At risk, or Blocked.") from exc
        values = [self.progress, self.next_steps, self.blockers, self.assistance]
        if not all(isinstance(value, str) and len(value) <= 1500 for value in values):
            raise UserError("Each response must contain at most 1,500 characters.")
        if not self.progress.strip() or not self.next_steps.strip():
            raise UserError("Progress and next steps are required; 'No progress' is acceptable.")
        return CheckinInput(status, *(value.strip() for value in values))

    @property
    def needs_support(self) -> bool:
        return self.status != Status.ON_TRACK or bool(self.blockers or self.assistance)


def utc_now() -> datetime:
    return datetime.now(UTC)


def stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(UTC).isoformat()


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UserError("Use an IANA timezone such as America/Chicago or UTC.") from exc


def parse_due(value: str, zone: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise UserError("Use YYYY-MM-DD HH:MM, optionally with a UTC offset.") from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    return localize(parsed, timezone(zone))


def localize(value: datetime, zone: ZoneInfo) -> datetime:
    """Reject ambiguous/nonexistent wall times instead of silently shifting deadlines."""
    first = value.replace(tzinfo=zone, fold=0)
    second = value.replace(tzinfo=zone, fold=1)
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != value:
        raise UserError("That local time does not exist due to daylight saving time.")
    if first.utcoffset() != second.utcoffset():
        raise UserError("That local time is ambiguous; specify an explicit UTC offset.")
    return first.astimezone(UTC)
