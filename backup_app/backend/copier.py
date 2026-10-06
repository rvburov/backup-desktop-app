"""Копирование файлов. Без Qt: сервис запускает BackupRunner.run() в отдельном потоке.

Исходные файлы никогда не изменяются, существующие копии никогда не перезаписываются.
Ошибка одного файла не прерывает копирование: она попадает в журнал и в BackupResult.errors.
Всё, что пропущено по правилам безопасности, попадает в BackupResult.skipped и в журнал
с меткой [SECURITY].

Копирование идёт в два прохода. Первый проход считает объём и записывает пропуски по правилам
безопасности. Второй проход копирует и записывает ошибки.
"""
import logging
import os
import shutil
import stat
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from . import safety
from .constants import BACKUP_FOLDER_PREFIX
from .logger import get_logger

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"

MB = 1024 * 1024
# Сколько записей каждого вида писать в журнал поштучно за одно копирование.
LOG_LIMIT = 200

ProgressCallback = Callable[[int, str], None]
WalkItem = Tuple[str, str, str, int]  # вид («dir» или «file»), путь, относительная папка, размер


@dataclass
class BackupJob:
    """Одно задание: источники одной вкладки и её папка назначения."""

    name: str = ""
    folders: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    destination: str = ""

    def has_sources(self) -> bool:
        return bool(self.folders or self.files)


@dataclass
class BackupOptions:
    copy_folder_contents: bool = False
    keep_history: bool = True
    create_backup_folder: bool = True


@dataclass
class BackupResult:
    status: str = STATUS_OK
    message: str = ""
    copied_count: int = 0
    copied_bytes: int = 0
    total_bytes: int = 0
    errors: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status == STATUS_OK

    @property
    def cancelled(self) -> bool:
        return self.status == STATUS_CANCELLED


def safe_destination_path(path: str, keep_history: bool) -> str:
    """Возвращает имя, по которому ничего не будет перезаписано."""
    if not os.path.exists(path):
        return path
    name, ext = os.path.splitext(path)
    if keep_history:
        stamped = f"{name}_{datetime.now().strftime('%d.%m.%Y_%H-%M-%S')}{ext}"
        if not os.path.exists(stamped):
            return stamped
        name, ext = os.path.splitext(stamped)
    counter = 1
    candidate = f"{name}_({counter}){ext}"
    while os.path.exists(candidate):
        counter += 1
        candidate = f"{name}_({counter}){ext}"
    return candidate


def free_space(path: str) -> Optional[int]:
    """Свободное место на диске или None, если узнать не удалось."""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def folder_copy_name(folder: str) -> str:
    """Имя папки в копии; для корня диска «C:\\» даёт «Диск_C»."""
    name = os.path.basename(os.path.normpath(folder))
    if not name or name.endswith(":"):
        name = "Диск_" + (folder.strip(":\\/") or "root")
    return name


class BackupRunner:
    """Выполняет одно копирование. Метод run() блокирующий, отмена через cancel() из другого потока."""

    PROGRESS_INTERVAL = 0.1

    def __init__(self, jobs: Iterable[BackupJob], options: BackupOptions,
                 policy: Optional[safety.SafetyPolicy] = None,
                 on_progress: Optional[ProgressCallback] = None):
        self.jobs = list(jobs)
        self.options = options
        self.policy = policy if policy is not None else safety.SafetyPolicy.default()
        self.on_progress = on_progress
        self.result = BackupResult()
        self.total_files = 0
        self.total_size = 0
        self._job_totals: List[Tuple[int, int]] = []
        self._cancel = threading.Event()
        self._last_report = 0.0
        self._protected = safety.ProtectedPaths(self.policy.protected_paths)
        self._destinations = [safety.normalize(job.destination) for job in self.jobs if job.destination]
        self._blocked_dirs: List[str] = []
        self._reported_access: Set[str] = set()
        self._log_counts: Dict[str, int] = {}
        self.log = get_logger()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ------------------------------------------------------------------ run
    def run(self) -> BackupResult:
        result = self.result
        try:
            self._scan()
            result.total_bytes = self.total_size
            if self.cancelled:
                return self._finish(STATUS_CANCELLED, "Операция отменена")
            if self.total_files == 0:
                return self._finish(STATUS_FAILED, "Нет файлов для копирования" + self._skipped_suffix())

            self._status(f"Начинаем копирование ({self.total_size / MB:.1f} MB)")
            for job, totals in zip(self.jobs, self._job_totals):
                if self.cancelled:
                    break
                self._copy_job(job, totals)

            skipped = self._skipped_suffix()
            if self.cancelled:
                return self._finish(STATUS_CANCELLED,
                                    f"Операция отменена (скопировано {result.copied_count} файлов)")
            if result.errors and result.copied_count == 0:
                return self._finish(STATUS_FAILED,
                                    f"Копирование не выполнено, ошибок: {len(result.errors)}{skipped}")
            if result.errors:
                return self._finish(STATUS_PARTIAL,
                                    f"Скопировано {result.copied_count} файлов, ошибок: {len(result.errors)}{skipped}")
            tabs = f" из {len(self.jobs)} вкладок" if len(self.jobs) > 1 else ""
            return self._finish(STATUS_OK, f"Успешно скопировано {result.copied_count} файлов{tabs}{skipped}")
        except Exception as error:  # защитный код: копирование не должно падать молча
            self.log.exception("Критическая ошибка копирования")
            result.errors.append(str(error))
            return self._finish(STATUS_FAILED, f"Критическая ошибка: {error}")

    def _finish(self, status: str, message: str) -> BackupResult:
        self.result.status = status
        self.result.message = message
        for kind, count in self._log_counts.items():
            if count > LOG_LIMIT:
                self.log.warning(f"{safety.SECURITY_TAG} Всего записей вида «{kind}»: {count}, "
                                 f"в журнал записаны первые {LOG_LIMIT}")
        self._report_progress(force=True)
        return self.result

    def _skipped_suffix(self) -> str:
        count = len(self.result.skipped)
        return f"; пропущено по правилам безопасности: {count}" if count else ""

    # ------------------------------------------------------------ проход 1
    def _scan(self) -> None:
        """Считает файлы и объём, записывает пропуски и ненайденные источники."""
        for job in self.jobs:
            count = size = 0
            for folder in job.folders:
                if self.cancelled:
                    return
                state, text = self._folder_state(folder, job)
                if state == "missing":
                    self._error(text)
                    continue
                if state == "skip":
                    self._skip(text)
                    continue
                if safety.is_link(folder):
                    self._note(f"Выбранная папка является ссылкой, копируется её содержимое: {folder}")
                for kind, _path, _rel, file_size in self._walk(folder, report=True, on_error=self._access_error):
                    if kind == "file":
                        count += 1
                        size += file_size
            for path in job.files:
                if self.cancelled:
                    return
                state, text, file_size = self._file_state(path)
                if state == "missing":
                    self._error(text)
                elif state == "skip":
                    self._skip(text)
                else:
                    count += 1
                    size += file_size
            self._job_totals.append((count, size))
            self.total_files += count
            self.total_size += size

    def _folder_state(self, folder: str, job: BackupJob) -> Tuple[str, str]:
        if not os.path.isdir(folder):
            return "missing", f"Папка не найдена, пропущена: {folder}"
        if self._protected.contains(folder):
            return "skip", f"Системная папка не копируется: {folder}"
        if job.destination and safety.normalize(folder) == safety.normalize(job.destination):
            return "skip", f"Папка совпадает с папкой назначения и не копируется: {folder}"
        return "ok", ""

    def _file_state(self, path: str) -> Tuple[str, str, int]:
        if not os.path.exists(path):
            return "missing", f"Файл не найден, пропущен: {path}", 0
        if self._protected.contains(path):
            return "skip", f"Системный файл не копируется: {path}", 0
        try:
            info = os.stat(path)  # явно выбранный файл: ссылка разрешается
        except OSError as error:
            return "missing", f"Нет доступа к файлу {path}: {error}", 0
        if not stat.S_ISREG(info.st_mode):
            return "skip", f"Пропущен специальный файл: {path}", 0
        if self.policy.max_file_size and info.st_size > self.policy.max_file_size:
            return "skip", f"Пропущен файл больше {self.policy.max_file_size_text}: {path}", 0
        return "ok", "", info.st_size

    def _walk(self, folder: str, report: bool,
              on_error: Optional[Callable[[str, OSError], None]] = None) -> Iterator[WalkItem]:
        """Обходит папку по правилам безопасности. Сначала выдаёт папку, затем её файлы."""
        prune = [root for root in self._destinations
                 if safety.is_inside(root, folder) and root != safety.normalize(folder)]
        stack = [(folder, "")]
        while stack:
            if self.cancelled:
                return
            current, relative = stack.pop()
            try:
                with os.scandir(current) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError as error:
                if on_error is not None:
                    on_error(current, error)
                continue
            yield "dir", current, relative, 0
            parent = safety.normalize(current)
            subdirs = []
            for entry in entries:
                if self.cancelled:
                    return
                kind, size = self._classify(entry, parent, prune, report, on_error)
                if kind == "dir":
                    subdirs.append((entry.path, os.path.join(relative, entry.name) if relative else entry.name))
                elif kind == "file":
                    yield "file", entry.path, relative, size
            stack.extend(reversed(subdirs))

    def _classify(self, entry: os.DirEntry, parent: str, prune: List[str], report: bool,
                  on_error: Optional[Callable[[str, OSError], None]]) -> Tuple[Optional[str], int]:
        path = entry.path
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as error:
            if on_error is not None:
                on_error(path, error)
            return None, 0
        if safety.entry_is_link(entry, info):
            if report:
                self._skip(f"Пропущена ссылка (symlink или junction): {path}")
            return None, 0
        if stat.S_ISDIR(info.st_mode):
            if self._protected.is_child(parent, path):
                if report:
                    self._skip(f"Пропущена системная папка: {path}")
                return None, 0
            if any(safety.is_inside(path, root) for root in prune):
                if report:
                    self._skip(f"Пропущена папка назначения внутри копируемой папки: {path}")
                return None, 0
            return "dir", 0
        if self._protected.is_child(parent, path):
            if report:
                self._skip(f"Пропущен системный файл: {path}")
            return None, 0
        if not stat.S_ISREG(info.st_mode):
            if report:
                self._skip(f"Пропущен специальный файл: {path}")
            return None, 0
        if self.policy.max_file_size and info.st_size > self.policy.max_file_size:
            if report:
                self._skip(f"Пропущен файл больше {self.policy.max_file_size_text}: {path}")
            return None, 0
        return "file", info.st_size

    # ------------------------------------------------------------ проход 2
    def _copy_job(self, job: BackupJob, totals: Tuple[int, int]) -> None:
        count, size = totals
        if len(self.jobs) > 1:
            self._status(f"Копирование вкладки '{job.name}'...")
        if not job.destination:
            self._error(f"Вкладка '{job.name}': не выбрана папка назначения")
            return
        if self._protected.contains(job.destination):
            self._error(f"Папка назначения находится в системной папке, вкладка '{job.name}' пропущена: "
                        f"{job.destination}", security=True)
            return
        if count == 0:
            return
        try:
            os.makedirs(job.destination, exist_ok=True)
        except OSError as error:
            self._error(f"Не удалось создать папку назначения {job.destination}: {error}")
            return
        free = free_space(job.destination)
        if free is not None and free < size:
            self._error(f"Недостаточно свободного места в {job.destination} "
                        f"для вкладки '{job.name}' (нужно {size / MB:.1f} MB)")
            return

        destination = job.destination
        if self.options.create_backup_folder:
            destination = os.path.join(destination, f"{BACKUP_FOLDER_PREFIX} {datetime.now().strftime('%d-%m-%Y')}")
            try:
                os.makedirs(destination, exist_ok=True)
            except OSError as error:
                self._error(f"Не удалось создать папку {destination}: {error}")
                return

        for folder in job.folders:
            if self.cancelled:
                return
            state, _text = self._folder_state(folder, job)
            if state == "ok":
                self._copy_folder(folder, destination, job.destination)
        for path in job.files:
            if self.cancelled:
                return
            state, _text, file_size = self._file_state(path)
            if state == "ok":
                self._copy_file(path, destination, file_size, job.destination)

    def _copy_folder(self, folder: str, destination: str, destination_root: str) -> None:
        if self.options.copy_folder_contents:
            base = destination
        else:
            base = safe_destination_path(os.path.join(destination, folder_copy_name(folder)),
                                         self.options.keep_history)
        for kind, path, relative, size in self._walk(folder, report=False, on_error=self._access_error):
            if self.cancelled:
                return
            if safety.has_parent_reference(relative):
                self._skip(f"Небезопасный относительный путь, пропущено: {path}")
                continue
            target_dir = os.path.join(base, relative) if relative else base
            if kind == "dir":
                self._make_dir(target_dir, path)
            else:
                self._copy_file(path, target_dir, size, destination_root)

    def _make_dir(self, target_dir: str, source_dir: str) -> None:
        if self._is_blocked(target_dir):
            return
        limit = self.policy.max_path_length
        if limit and len(target_dir) > limit:
            self._blocked_dirs.append(target_dir)
            self._skip(f"Путь папки в копии длиннее {limit} символов, папка пропущена: {source_dir}")
            return
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as error:
            self._blocked_dirs.append(target_dir)
            self._error(f"Не удалось создать папку {target_dir}: {error}")

    def _is_blocked(self, path: str) -> bool:
        return any(path == blocked or path.startswith(blocked + os.sep) for blocked in self._blocked_dirs)

    def _copy_file(self, source: str, target_dir: str, size: int, destination_root: str) -> None:
        if self._is_blocked(target_dir):
            self._skip(f"Файл в пропущенной папке: {source}", log=False)
            return
        target, shortened = self._target_path(target_dir, os.path.basename(source))
        if target is None:
            self._skip(f"Путь копии длиннее {self.policy.max_path_length} символов, файл пропущен: {source}")
            return
        if not safety.is_inside(target, destination_root):
            self._skip(f"Путь копии выходит за пределы папки назначения, файл пропущен: {source}")
            return
        try:
            shutil.copy2(source, target)
        except Exception as error:
            self._error(f"Ошибка при копировании файла {source}: {error}")
            return
        if shortened:
            self._note(f"Имя файла укорочено до {len(os.path.basename(target))} символов: "
                       f"{source} -> {os.path.basename(target)}")
        self.result.copied_bytes += size
        self.result.copied_count += 1
        self._report_progress()

    def _target_path(self, directory: str, name: str) -> Tuple[Optional[str], bool]:
        """Путь копии с учётом совпадения имён и лимита длины пути."""
        keep_history = self.options.keep_history
        path = safe_destination_path(os.path.join(directory, name), keep_history)
        limit = self.policy.max_path_length
        if not limit or len(path) <= limit:
            return path, False
        budget = limit - len(directory) - 1 - safety.NAME_SUFFIX_RESERVE
        short = safety.shorten_name(name, budget)
        if short is None:
            return None, False
        path = safe_destination_path(os.path.join(directory, short), keep_history)
        if len(path) > limit:
            return None, False
        return path, True

    # ------------------------------------------------------- журнал, прогресс
    def _access_error(self, path: str, error: OSError) -> None:
        """Ошибка доступа при обходе. Каждый путь записывается один раз за копирование."""
        if path in self._reported_access:
            return
        self._reported_access.add(path)
        self._error(f"Нет доступа к {path}: {error}", security=True)

    def _error(self, text: str, security: bool = False) -> None:
        self.result.errors.append(text)
        message = f"{safety.SECURITY_TAG} {text}" if security else text
        self._log_limited("ошибка", logging.ERROR, message)

    def _skip(self, text: str, log: bool = True) -> None:
        self.result.skipped.append(text)
        if log:
            self._log_limited("пропуск", logging.WARNING, f"{safety.SECURITY_TAG} {text}")

    def _note(self, text: str) -> None:
        self._log_limited("уведомление", logging.INFO, f"{safety.SECURITY_TAG} {text}")

    def _log_limited(self, kind: str, level: int, message: str) -> None:
        count = self._log_counts.get(kind, 0) + 1
        self._log_counts[kind] = count
        if count <= LOG_LIMIT:
            self.log.log(level, message)
        elif count == LOG_LIMIT + 1:
            self.log.log(level, f"{safety.SECURITY_TAG} Слишком много записей вида «{kind}», "
                                f"остальные не пишутся в журнал")

    def _percent(self) -> int:
        if self.total_size > 0:
            return min(100, int(self.result.copied_bytes * 100 / self.total_size))
        if self.total_files > 0:
            return min(100, int(self.result.copied_count * 100 / self.total_files))
        return 0

    def _status(self, text: str) -> None:
        self._emit_progress(self._percent(), text)

    def _report_progress(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_report < self.PROGRESS_INTERVAL:
            return
        self._last_report = now
        result = self.result
        self._emit_progress(self._percent(),
                            f"Копирование... ({result.copied_bytes / MB:.1f} MB / {self.total_size / MB:.1f} MB) "
                            f"| Файлов: {result.copied_count}")

    def _emit_progress(self, percent: int, text: str) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(percent, text)
        except Exception:  # защитный код: ошибка обработчика не должна прерывать копирование
            self.log.exception("Ошибка обработчика прогресса")
