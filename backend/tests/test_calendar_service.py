from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.services.calendar import CalendarError, WorkCalendar

IST = ZoneInfo("Asia/Kolkata")


def cal(days="123456", start=time(9), end=time(18), holidays=()) -> WorkCalendar:
    return WorkCalendar(
        working_days=frozenset(int(d) for d in days),
        shift_start=start,
        shift_end=end,
        holidays=frozenset(holidays),
        time_zone=IST,
    )


def at(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# 2026-10-02 is a Friday; 10-04 Sunday; 10-05 Monday.


def test_minutes_per_day() -> None:
    assert cal().minutes_per_day == 540
    assert cal(start=time(8, 30), end=time(17)).minutes_per_day == 510


@pytest.mark.parametrize(
    ("start", "minutes", "expected"),
    [
        (at(2026, 10, 2, 10), 60, at(2026, 10, 2, 11)),  # inside the shift
        (at(2026, 10, 2, 7), 60, at(2026, 10, 2, 10)),  # before the shift starts
        (at(2026, 10, 2, 17), 120, at(2026, 10, 3, 10)),  # spills into Saturday
        (at(2026, 10, 3, 17), 120, at(2026, 10, 5, 10)),  # skips Sunday
        (at(2026, 10, 2, 20), 30, at(2026, 10, 3, 9, 30)),  # after the shift ends
        (at(2026, 10, 2, 9), 540, at(2026, 10, 2, 18)),  # exactly one day
        (at(2026, 10, 2, 9), 541, at(2026, 10, 3, 9, 1)),
        (at(2026, 10, 2, 13), 0, at(2026, 10, 2, 13)),
    ],
)
def test_add_working_minutes(start, minutes, expected) -> None:
    assert cal().add_working_minutes(start, minutes) == expected


def test_holidays_are_skipped() -> None:
    calendar = cal(holidays=[date(2026, 10, 3)])
    assert calendar.add_working_minutes(at(2026, 10, 2, 17), 120) == at(2026, 10, 5, 10)
    assert not calendar.is_working_day(date(2026, 10, 3))


def test_five_day_week() -> None:
    assert cal("12345").add_working_minutes(at(2026, 10, 2, 17), 120) == at(2026, 10, 5, 10)


def test_add_working_days() -> None:
    calendar = cal()
    assert calendar.add_working_days(date(2026, 10, 3), 0) == date(2026, 10, 3)
    assert calendar.add_working_days(date(2026, 10, 4), 0) == date(2026, 10, 5)
    assert calendar.add_working_days(date(2026, 10, 2), 2) == date(2026, 10, 5)
    assert cal(holidays=[date(2026, 10, 5)]).add_working_days(date(2026, 10, 2), 2) == date(
        2026, 10, 6
    )


def test_working_minutes_between_is_inverse_of_add() -> None:
    calendar = cal(holidays=[date(2026, 10, 6)])
    start = at(2026, 10, 2, 15, 20)
    for minutes in (0, 1, 100, 540, 1000, 5000):
        finish = calendar.add_working_minutes(start, minutes)
        assert calendar.working_minutes_between(start, finish) == minutes


def test_working_minutes_between_edges() -> None:
    calendar = cal()
    assert calendar.working_minutes_between(at(2026, 10, 2, 12), at(2026, 10, 2, 11)) == 0
    assert calendar.working_minutes_between(at(2026, 10, 3, 18), at(2026, 10, 5, 9)) == 0
    assert calendar.working_minutes_between(at(2026, 10, 2, 0), at(2026, 10, 6, 0)) == 3 * 540


def test_other_timezone_input_is_converted() -> None:
    utc_start = datetime(2026, 10, 2, 4, 30, tzinfo=ZoneInfo("UTC"))  # 10:00 IST
    assert cal().add_working_minutes(utc_start, 60) == at(2026, 10, 2, 11)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"days": ""},
        {"days": "8"},
        {"start": time(18), "end": time(9)},
    ],
)
def test_invalid_calendars_are_rejected(kwargs) -> None:
    with pytest.raises(CalendarError):
        cal(**kwargs)


def test_naive_and_negative_inputs_are_rejected() -> None:
    with pytest.raises(CalendarError):
        cal().add_working_minutes(datetime(2026, 10, 2, 10), 10)
    with pytest.raises(CalendarError):
        cal().add_working_minutes(at(2026, 10, 2, 10), -1)
    with pytest.raises(CalendarError):
        cal().add_working_days(date(2026, 10, 2), -1)
