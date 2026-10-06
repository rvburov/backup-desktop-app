from datetime import datetime, time

from backup_app.backend.scheduler import (PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_WEEKLY, Schedule,
                                          format_run_time, next_run, parse_time, previous_run)

TEN = time(10, 0)


def daily():
    return Schedule(PERIOD_DAILY, TEN)


def weekly(weekday):
    return Schedule(PERIOD_WEEKLY, TEN, weekday=weekday)


def monthly(monthday):
    return Schedule(PERIOD_MONTHLY, TEN, monthday=monthday)


def test_daily_before_time_is_today():
    assert next_run(daily(), datetime(2026, 10, 6, 9, 0)) == datetime(2026, 10, 6, 10, 0)


def test_daily_after_time_is_tomorrow():
    assert next_run(daily(), datetime(2026, 10, 6, 11, 0)) == datetime(2026, 10, 7, 10, 0)


def test_daily_exactly_at_time_rolls_to_tomorrow():
    assert next_run(daily(), datetime(2026, 10, 6, 10, 0)) == datetime(2026, 10, 7, 10, 0)


def test_weekly_tuesday_to_friday():
    assert next_run(weekly(4), datetime(2026, 10, 6, 11, 0)) == datetime(2026, 10, 9, 10, 0)


def test_weekly_same_day_after_time_is_next_week():
    assert next_run(weekly(4), datetime(2026, 10, 9, 11, 0)) == datetime(2026, 10, 16, 10, 0)


def test_weekly_same_day_before_time_is_today():
    assert next_run(weekly(4), datetime(2026, 10, 9, 9, 0)) == datetime(2026, 10, 9, 10, 0)


def test_monthly_31_in_february_is_clamped_to_28():
    assert next_run(monthly(31), datetime(2026, 2, 10, 11, 0)) == datetime(2026, 2, 28, 10, 0)


def test_monthly_31_computed_on_feb_28_evening_is_march_31():
    # Регрессия: раньше обрезанный день (28) переносился на следующий месяц.
    assert next_run(monthly(31), datetime(2026, 2, 28, 23, 0)) == datetime(2026, 3, 31, 10, 0)


def test_monthly_31_on_jan_31_after_time_is_feb_28():
    assert next_run(monthly(31), datetime(2026, 1, 31, 11, 0)) == datetime(2026, 2, 28, 10, 0)


def test_monthly_1_on_dec_31_is_next_year():
    assert next_run(monthly(1), datetime(2026, 12, 31, 11, 0)) == datetime(2027, 1, 1, 10, 0)


def test_monthly_leap_year():
    assert next_run(monthly(30), datetime(2028, 2, 1, 0, 0)) == datetime(2028, 2, 29, 10, 0)


def test_previous_daily():
    assert previous_run(daily(), datetime(2026, 10, 6, 9, 0)) == datetime(2026, 10, 5, 10, 0)
    assert previous_run(daily(), datetime(2026, 10, 6, 11, 0)) == datetime(2026, 10, 6, 10, 0)


def test_previous_weekly():
    assert previous_run(weekly(4), datetime(2026, 10, 6, 11, 0)) == datetime(2026, 10, 2, 10, 0)
    assert previous_run(weekly(4), datetime(2026, 10, 9, 9, 0)) == datetime(2026, 10, 2, 10, 0)
    assert previous_run(weekly(4), datetime(2026, 10, 9, 11, 0)) == datetime(2026, 10, 9, 10, 0)


def test_previous_monthly():
    assert previous_run(monthly(31), datetime(2026, 3, 15, 0, 0)) == datetime(2026, 2, 28, 10, 0)
    assert previous_run(monthly(31), datetime(2026, 3, 31, 11, 0)) == datetime(2026, 3, 31, 10, 0)
    assert previous_run(monthly(1), datetime(2027, 1, 1, 9, 0)) == datetime(2026, 12, 1, 10, 0)


def test_previous_is_before_next():
    now = datetime(2026, 10, 6, 12, 34)
    for schedule in (daily(), weekly(0), weekly(6), monthly(1), monthly(31)):
        assert previous_run(schedule, now) <= now < next_run(schedule, now)


def test_parse_time():
    assert parse_time("09:30") == time(9, 30)
    assert parse_time("9:5") == time(9, 5)
    assert parse_time("bad") == time(0, 0)
    assert parse_time("bad", None) is None
    assert parse_time("25:00", None) is None


def test_format_run_time():
    assert format_run_time(datetime(2026, 10, 7, 9, 5, 0)) == "07.10.2026 09:05:00"
