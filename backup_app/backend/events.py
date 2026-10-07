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
    tab_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BackupProgress:
    percent: int
    text: str


@dataclass(frozen=True)
class BackupFinished:
    result: BackupResult
    scheduled: bool
    tab_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RunSkipped:
    """Копирование не запущено: нет источников, нет папки назначения или уже идет другое."""

    scheduled: bool
    reason: str


@dataclass(frozen=True)
class ScheduleChanged:
    """Расписание вкладок изменилось: (идентификатор вкладки, следующее копирование) каждой
    вкладки с включенным расписанием, в порядке вкладок."""

    next_runs: Tuple[Tuple[str, datetime], ...] = ()

    @property
    def active(self) -> bool:
        """Расписание включено хотя бы у одной вкладки."""
        return bool(self.next_runs)

    @property
    def nearest(self) -> Optional[Tuple[str, datetime]]:
        """Ближайшее копирование по расписанию: (идентификатор вкладки, время) или None."""
        if not self.next_runs:
            return None
        return min(self.next_runs, key=lambda item: item[1])

    @property
    def next_run(self) -> Optional[datetime]:
        """Время ближайшего копирования по расписанию или None."""
        nearest = self.nearest
        return nearest[1] if nearest else None


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
