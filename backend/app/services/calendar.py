"""Deterministic working-time arithmetic for a site calendar.

Times are timezone-aware; each calendar works in its site's local time. A working day has one
continuous shift from shift_start to shift_end (breaks and overnight shifts are not modelled).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MAX_SEARCH_DAYS = 3660


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class WorkCalendar:
    working_days: frozenset[int]
    shift_start: time
    shift_end: time
    holidays: frozenset[date]
    time_zone: ZoneInfo

    def __post_init__(self) -> None:
        if not self.working_days or not self.working_days <= set(range(1, 8)):
            raise CalendarError("A calendar needs at least one working weekday (1-7)")
        if self.shift_end <= self.shift_start:
            raise CalendarError("The shift must end after it starts")

    @property
    def minutes_per_day(self) -> int:
        start = self.shift_start.hour * 60 + self.shift_start.minute
        end = self.shift_end.hour * 60 + self.shift_end.minute
        return end - start

    def is_working_day(self, day: date) -> bool:
        return day.isoweekday() in self.working_days and day not in self.holidays

    def _shift(self, day: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(day, self.shift_start, self.time_zone),
            datetime.combine(day, self.shift_end, self.time_zone),
        )

    def next_working_day(self, day: date) -> date:
        for offset in range(MAX_SEARCH_DAYS):
            candidate = day + timedelta(days=offset)
            if self.is_working_day(candidate):
                return candidate
        raise CalendarError("No working day found within ten years")

    def add_working_days(self, day: date, days: int) -> date:
        """The date `days` working days after `day` (0 = next working day on or after `day`)."""
        if days < 0:
            raise CalendarError("Use a non-negative number of working days")
        current = self.next_working_day(day)
        for _ in range(days):
            current = self.next_working_day(current + timedelta(days=1))
        return current

    def add_working_minutes(self, start: datetime, minutes: int) -> datetime:
        """When work of `minutes` working minutes finishes if started at `start`."""
        if start.tzinfo is None:
            raise CalendarError("Use a timezone-aware start time")
        if minutes < 0:
            raise CalendarError("Use a non-negative number of minutes")
        if minutes == 0:
            return start
        local = start.astimezone(self.time_zone)
        day = local.date()
        remaining = minutes
        for _ in range(MAX_SEARCH_DAYS):
            if self.is_working_day(day):
                shift_start, shift_end = self._shift(day)
                begin = max(local, shift_start)
                if begin < shift_end:
                    available = int((shift_end - begin).total_seconds() // 60)
                    if remaining <= available:
                        return begin + timedelta(minutes=remaining)
                    remaining -= available
            day += timedelta(days=1)
            local = datetime.combine(day, time.min, self.time_zone)
        raise CalendarError("The work does not fit within ten years")

    def working_minutes_between(self, start: datetime, end: datetime) -> int:
        """Working minutes in [start, end); zero when end is not after start."""
        if start.tzinfo is None or end.tzinfo is None:
            raise CalendarError("Use timezone-aware times")
        if end <= start:
            return 0
        local_start = start.astimezone(self.time_zone)
        local_end = end.astimezone(self.time_zone)
        total = 0
        day = local_start.date()
        while day <= local_end.date():
            if self.is_working_day(day):
                shift_start, shift_end = self._shift(day)
                begin = max(local_start, shift_start)
                finish = min(local_end, shift_end)
                if finish > begin:
                    total += int((finish - begin).total_seconds() // 60)
            day += timedelta(days=1)
        return total
