"""Расчёт времени планового копирования. Чистые функции без Qt."""
import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

PERIOD_DAILY = "Ежедневно"
PERIOD_WEEKLY = "Еженедельно"
PERIOD_MONTHLY = "Ежемесячно"
PERIODS = (PERIOD_DAILY, PERIOD_WEEKLY, PERIOD_MONTHLY)

WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")


@dataclass(frozen=True)
class Schedule:
    period: str = PERIOD_DAILY
    backup_time: time = time(0, 0)
    weekday: int = 0      # 0 = понедельник
    monthday: int = 1     # 1..31, обрезается до последнего дня месяца


def _at(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment)


def _month_occurrence(year: int, month: int, monthday: int, moment: time) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(monthday, last_day), moment.hour, moment.minute, moment.second)


def _shift_month(year: int, month: int, delta: int):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def next_run(schedule: Schedule, now: Optional[datetime] = None) -> datetime:
    """Ближайший момент запуска строго после now."""
    now = now or datetime.now()
    moment = schedule.backup_time

    if schedule.period == PERIOD_WEEKLY:
        days_ahead = (schedule.weekday - now.weekday()) % 7
        candidate = _at(now.date() + timedelta(days=days_ahead), moment)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    if schedule.period == PERIOD_MONTHLY:
        candidate = _month_occurrence(now.year, now.month, schedule.monthday, moment)
        if candidate <= now:
            year, month = _shift_month(now.year, now.month, 1)
            candidate = _month_occurrence(year, month, schedule.monthday, moment)
        return candidate

    candidate = _at(now.date(), moment)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def previous_run(schedule: Schedule, now: Optional[datetime] = None) -> datetime:
    """Последний момент запуска, не позже now. Нужен для проверки пропущенных копирований."""
    now = now or datetime.now()
    moment = schedule.backup_time

    if schedule.period == PERIOD_WEEKLY:
        days_back = (now.weekday() - schedule.weekday) % 7
        candidate = _at(now.date() - timedelta(days=days_back), moment)
        if candidate > now:
            candidate -= timedelta(days=7)
        return candidate

    if schedule.period == PERIOD_MONTHLY:
        candidate = _month_occurrence(now.year, now.month, schedule.monthday, moment)
        if candidate > now:
            year, month = _shift_month(now.year, now.month, -1)
            candidate = _month_occurrence(year, month, schedule.monthday, moment)
        return candidate

    candidate = _at(now.date(), moment)
    if candidate > now:
        candidate -= timedelta(days=1)
    return candidate


def parse_time(text: str, default: Optional[time] = time(0, 0)) -> Optional[time]:
    """Разбирает строку «чч:мм»; при ошибке возвращает default."""
    try:
        hours, minutes = str(text).strip().split(":")[:2]
        return time(int(hours), int(minutes))
    except (ValueError, TypeError, AttributeError):
        return default


def format_run_time(moment: datetime) -> str:
    return moment.strftime("%d.%m.%Y %H:%M:%S")
