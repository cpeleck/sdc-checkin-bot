from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .models import UserError, localize, timezone


@dataclass(frozen=True)
class WeeklySchedule:
    open_day: int
    open_time: str
    close_day: int
    close_time: str

    @classmethod
    def parse(cls, open_day: int, open_time: str, close_day: int, close_time: str):
        try:
            opening = time.fromisoformat(open_time)
            closing = time.fromisoformat(close_time)
            if not 0 <= open_day <= 6 or not 0 <= close_day <= 6:
                raise ValueError
            if (
                opening.tzinfo
                or closing.tzinfo
                or opening.second
                or closing.second
                or opening.microsecond
                or closing.microsecond
            ):
                raise ValueError
            if (open_day, opening) == (close_day, closing):
                raise ValueError
            # Overnight DST transitions are needlessly ambiguous for recurring rounds.
            if opening.hour < 3 or closing.hour < 3:
                raise UserError("Use recurring times at or after 03:00 to avoid DST transitions.")
        except ValueError as exc:
            raise UserError(
                "Use weekdays 0–6 (Monday–Sunday) and HH:MM times; opening and closing must differ."
            ) from exc
        return cls(open_day, opening.strftime("%H:%M"), close_day, closing.strftime("%H:%M"))

    def window(self, now: datetime, zone_name: str) -> tuple[datetime, datetime]:
        zone = timezone(zone_name)
        local = now.astimezone(zone)
        start_day = local.date() - timedelta(days=(local.weekday() - self.open_day) % 7)
        start_local = datetime.combine(start_day, time.fromisoformat(self.open_time))
        if start_local > local.replace(tzinfo=None):
            start_local -= timedelta(days=7)
        end_local = datetime.combine(
            start_local.date() + timedelta(days=(self.close_day - self.open_day) % 7),
            time.fromisoformat(self.close_time),
        )
        if end_local <= start_local:
            end_local += timedelta(days=7)
        return localize(start_local, zone), localize(end_local, zone)
