"""История копирования: когда и что копировалось и чем это закончилось.

История показывается в окне и хранится в текстовом файле рядом с настройками, поэтому
переживает перезапуск приложения. Служебные сообщения и технические подробности ошибок
сюда не попадают: они пишутся только в подробный журнал (модуль logger).

Формат файла: запись начинается строкой «дд.мм.гггг чч:мм  текст», подробности записи
идут следующими строками с отступом. Записи старше срока хранения удаляются.
"""
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Sequence, Tuple

from .logger import get_logger

TIME_FORMAT = "%d.%m.%Y %H:%M"
RETENTION_DAYS = 365
# Сколько подробностей (ошибок и пропущенных файлов) хранить у одной записи.
MAX_DETAILS = 20
DETAIL_INDENT = " " * 20

ICON_OK = "✓"
ICON_WARNING = "⚠"
ICON_ERROR = "✗"

_HEAD = re.compile(r"(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})  (\S.*)")


@dataclass(frozen=True)
class HistoryEntry:
    """Одна запись истории: время, текст и подробности, например список ошибок."""

    time: datetime
    text: str
    details: Tuple[str, ...] = ()

    def lines(self) -> List[str]:
        """Строки записи в том виде, в каком они показываются в окне и хранятся в файле."""
        head = f"{self.time.strftime(TIME_FORMAT)}  {self.text}"
        return [head] + [DETAIL_INDENT + detail for detail in self.details]


def limit_details(details: Sequence[str], limit: int = MAX_DETAILS) -> Tuple[str, ...]:
    """Первые limit подробностей и строка о количестве остальных."""
    items = [detail for detail in details if detail]
    if len(items) <= limit:
        return tuple(items)
    return tuple(items[:limit]) + (f"…и еще {len(items) - limit}, см. подробный журнал",)


def parse_history(text: str) -> List[HistoryEntry]:
    """Записи из текста файла истории. Строки, которые не удалось разобрать, пропускаются."""
    parsed: List[Tuple[datetime, str, List[str]]] = []
    current: Optional[Tuple[datetime, str, List[str]]] = None
    for line in text.splitlines():
        match = _HEAD.fullmatch(line.rstrip())
        if match:
            current = None
            try:
                moment = datetime.strptime(match.group(1), TIME_FORMAT)
            except ValueError:
                continue
            current = (moment, match.group(2), [])
            parsed.append(current)
        elif not line.strip():
            continue
        elif line[:1].isspace() and current is not None:
            current[2].append(line.strip())
        else:
            current = None
    return [HistoryEntry(moment, entry_text, tuple(details)) for moment, entry_text, details in parsed]


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        return handle.read()


class HistoryStore:
    """Файл истории копирования. Методы можно вызывать из любого потока."""

    def __init__(self, path: str, retention_days: int = RETENTION_DAYS,
                 now: Callable[[], datetime] = datetime.now):
        self.path = path
        self._retention = timedelta(days=retention_days)
        self._now = now
        self._lock = threading.Lock()
        self._entries: Optional[List[HistoryEntry]] = None
        self._can_rewrite = True

    def entries(self) -> List[HistoryEntry]:
        """Записи за срок хранения, от старых к новым."""
        with self._lock:
            return list(self._loaded())

    def add(self, entry: HistoryEntry) -> None:
        """Добавляет запись. Ошибку записи файла передает вызывающему как OSError."""
        with self._lock:
            entries = self._loaded()
            entries.append(entry)
            if self._drop_expired(entries) and self._can_rewrite:
                self._rewrite(entries)
            else:
                self._append(entry)

    def _loaded(self) -> List[HistoryEntry]:
        if self._entries is None:
            try:
                text = _read_text(self.path)
            except FileNotFoundError:
                text = ""
            except OSError as error:
                # Файл есть, но не читается: перезапись уничтожила бы записи, поэтому только дописываем.
                get_logger().error(f"Не удалось прочитать историю копирования {self.path}: {error}")
                text = ""
                self._can_rewrite = False
            self._entries = parse_history(text)
            if self._drop_expired(self._entries) and self._can_rewrite:
                try:
                    self._rewrite(self._entries)
                except OSError as error:
                    get_logger().error(f"Не удалось удалить старые записи истории копирования: {error}")
        return self._entries

    def _drop_expired(self, entries: List[HistoryEntry]) -> bool:
        cutoff = self._now() - self._retention
        kept = [entry for entry in entries if entry.time >= cutoff]
        if len(kept) == len(entries):
            return False
        entries[:] = kept
        return True

    def _append(self, entry: HistoryEntry) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(entry.lines()) + "\n")

    def _rewrite(self, entries: List[HistoryEntry]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write("\n".join(entry.lines()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self.path)
