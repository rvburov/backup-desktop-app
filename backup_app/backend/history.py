"""История копирования: когда и что копировалось и чем это закончилось.

История показывается в окне и хранится в текстовом файле рядом с настройками, поэтому
переживает перезапуск приложения. Служебные сообщения и технические подробности ошибок
сюда не попадают: они пишутся только в подробный журнал (модуль logger).

Формат файла: запись начинается строкой «дд.мм.гггг чч:мм  текст», подробности записи
идут следующими строками с отступом. Если запись относится к вкладкам, сразу за первой
строкой идет строка «#tabs: id1 id2» с тем же отступом: по ней окно отбирает записи вкладки.
Файлы прежних версий без этой строки читаются как раньше. Записи старше срока хранения удаляются.
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
TABS_MARK = "#tabs:"

ICON_OK = "✓"
ICON_WARNING = "⚠"
ICON_ERROR = "✗"

_HEAD = re.compile(r"(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})  (\S.*)")


@dataclass(frozen=True)
class HistoryEntry:
    """Одна запись истории: время, текст, подробности (например, список ошибок) и вкладки записи."""

    time: datetime
    text: str
    details: Tuple[str, ...] = ()
    tab_ids: Tuple[str, ...] = ()

    def lines(self) -> List[str]:
        """Строки записи в том виде, в каком они показываются в окне (без вкладок)."""
        head = f"{self.time.strftime(TIME_FORMAT)}  {self.text}"
        return [head] + [DETAIL_INDENT + detail for detail in self.details]

    def file_lines(self) -> List[str]:
        """Строки записи в файле истории: после первой строки идет строка вкладок."""
        lines = self.lines()
        if self.tab_ids:
            lines.insert(1, f"{DETAIL_INDENT}{TABS_MARK} {' '.join(self.tab_ids)}")
        return lines


def limit_details(details: Sequence[str], limit: int = MAX_DETAILS) -> Tuple[str, ...]:
    """Первые limit подробностей и строка о количестве остальных."""
    items = [detail for detail in details if detail]
    if len(items) <= limit:
        return tuple(items)
    return tuple(items[:limit]) + (f"…и еще {len(items) - limit}, см. подробный журнал",)


class _Parsed:
    """Запись при разборе файла: подробности и вкладки набираются построчно."""

    def __init__(self, moment: datetime, text: str):
        self.moment = moment
        self.text = text
        self.details: List[str] = []
        self.tab_ids: Tuple[str, ...] = ()
        self.started = False  # после первой строки уже были строки с отступом

    def add(self, line: str) -> None:
        if not self.started and line.startswith(TABS_MARK):
            self.tab_ids = tuple(line[len(TABS_MARK):].split())
        else:
            self.details.append(line)
        self.started = True

    def entry(self) -> HistoryEntry:
        return HistoryEntry(self.moment, self.text, tuple(self.details), self.tab_ids)


def parse_history(text: str) -> List[HistoryEntry]:
    """Записи из текста файла истории. Строки, которые не удалось разобрать, пропускаются."""
    parsed: List[_Parsed] = []
    current: Optional[_Parsed] = None
    for line in text.splitlines():
        match = _HEAD.fullmatch(line.rstrip())
        if match:
            current = None
            try:
                moment = datetime.strptime(match.group(1), TIME_FORMAT)
            except ValueError:
                continue
            current = _Parsed(moment, match.group(2))
            parsed.append(current)
        elif not line.strip():
            continue
        elif line[:1].isspace() and current is not None:
            current.add(line.strip())
        else:
            current = None
    return [item.entry() for item in parsed]


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
            handle.write("\n".join(entry.file_lines()) + "\n")

    def _rewrite(self, entries: List[HistoryEntry]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write("\n".join(entry.file_lines()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self.path)
