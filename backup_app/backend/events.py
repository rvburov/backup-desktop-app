"""События, которыми сервис сообщает интерфейсу о происходящем.

События приходят из фоновых потоков сервиса. Интерфейс сам переносит их в свой поток.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from .copier import BackupResult
from .history import HistoryEntry
from .settings_store import AppConfig


@dataclass(frozen=True)
class BackupStarted:
    scheduled: bool
    tab_names: Tuple[str, ...]


@dataclass(frozen=True)
class BackupProgress:
    percent: int
    text: str


@dataclass(frozen=True)
class BackupFinished:
    result: BackupResult
    scheduled: bool


@dataclass(frozen=True)
class RunSkipped:
    """Копирование не запущено: нет источников, нет папки назначения или уже идет другое."""

    scheduled: bool
    reason: str


@dataclass(frozen=True)
class ScheduleChanged:
    active: bool
    next_run: Optional[datetime]


@dataclass(frozen=True)
class ConfigChanged:
    """Настройки изменились не по команде окна: сброс или синхронизация автозапуска."""

    config: AppConfig


@dataclass(frozen=True)
class HistoryAdded:
    """Новая запись истории копирования."""

    entry: HistoryEntry


@dataclass(frozen=True)
class AppProblem:
    """Сбой самого приложения, не связанный с копированием: например, не сохранились настройки."""

    title: str
    text: str
