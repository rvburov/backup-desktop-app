"""Копирование файлов. Без Qt: сервис запускает BackupRunner.run() в отдельном потоке.

Исходные файлы никогда не изменяются, существующие копии никогда не перезаписываются.
Ошибка одного файла не прерывает копирование: она попадает в журнал и в BackupResult.errors.
Все, что пропущено по правилам безопасности, попадает в BackupResult.skipped и в журнал
с меткой [SECURITY]. Файлы, не скопированные из-за лимита размера или длины пути, еще и
в BackupResult.over_limit: это данные пользователя, поэтому их показывает история копирования.

Копирование идет в два прохода. Первый проход считает объем и записывает пропуски по правилам
безопасности. Второй проход копирует и записывает ошибки.

Параметр «Копировать только новые и измененные файлы» (copy_only_changed): копия лежит по постоянным
путям, неизмененные файлы (тот же размер и время изменения) пропускаются. Прежняя копия измененного
файла не перезаписывается, а переименовывается: к имени добавляется дата ее изменения.
"""
import errno
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
from .constants import BACKUP_FOLDER_DATE_FORMAT, BACKUP_FOLDER_PREFIX, COPY_STAMP_FORMAT
from .logger import get_logger
from .wording import count_files, count_tabs_genitive

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"

MB = 1024 * 1024
# Сколько записей каждого вида писать в журнал поштучно за одно копирование.
LOG_LIMIT = 200
# Файл не изменился, если у копии тот же размер, а время изменения отличается не больше чем
# на 2 секунды: FAT хранит время с шагом 2 секунды.
SAME_TIME_TOLERANCE = 2.0
# Сколько номеров перебирать для имени прежней копии, если имя с той же датой уже занято.
VERSION_ATTEMPTS = 1000

ProgressCallback = Callable[[int, str], None]
WalkItem = Tuple[str, str, str, int, float]  # вид («dir» или «file»), путь, относительная папка, размер, время изменения


@dataclass
class BackupOptions:
    """Параметры копирования; по умолчанию все выключены, как у новой вкладки."""

    copy_folder_contents: bool = False
    keep_history: bool = False
    create_backup_folder: bool = False
    copy_only_changed: bool = False


@dataclass
class BackupJob:
    """Одно задание: источники одной вкладки, ее папка назначения и ее параметры копирования.

    Если options не заданы, действуют общие параметры копирования (BackupRunner.options).
    """

    name: str = ""
    folders: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    destination: str = ""
    options: Optional[BackupOptions] = None

    def has_sources(self) -> bool:
        return bool(self.folders or self.files)


@dataclass
class BackupResult:
    status: str = STATUS_OK
    message: str = ""
    copied_count: int = 0
    copied_bytes: int = 0
    total_bytes: int = 0
    errors: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    over_limit: List[str] = field(default_factory=list)  # часть skipped: больше лимита размера или длины пути
    unchanged_count: int = 0  # «только новые и измененные»: файлы, копия которых уже есть

    @property
    def success(self) -> bool:
        return self.status == STATUS_OK

    @property
    def cancelled(self) -> bool:
        return self.status == STATUS_CANCELLED


def backup_folder_name(moment: Optional[datetime] = None) -> str:
    """Имя папки копии за день: «Резервное копирование дд-мм-гггг»."""
    return f"{BACKUP_FOLDER_PREFIX} {(moment or datetime.now()).strftime(BACKUP_FOLDER_DATE_FORMAT)}"


def safe_destination_path(path: str, keep_history: bool) -> str:
    """Возвращает имя, по которому ничего не будет перезаписано."""
    if not os.path.exists(path):
        return path
    name, ext = os.path.splitext(path)
    if keep_history:
        stamped = f"{name}_{datetime.now().strftime(COPY_STAMP_FORMAT)}{ext}"
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
    """Имя папки в копии; для корня диска «C:\\» дает «Диск_C»."""
    name = os.path.basename(os.path.normpath(folder))
    if not name or name.endswith(":"):
        name = "Диск_" + (folder.strip(":\\/") or "root")
    return name


# Понятные причины частых ошибок для истории копирования. Технический текст ошибки
# пишется только в подробный журнал.
_WINERROR_TEXTS = {
    2: "файл не найден",
    3: "путь не найден",
    5: "нет доступа",
    21: "диск не готов",
    32: "файл занят другой программой",
    33: "файл заблокирован другой программой",
    53: "сетевой путь недоступен",
    64: "сетевое подключение прервано",
    67: "сетевой путь недоступен",
    112: "на диске недостаточно места",
    206: "слишком длинное имя или путь",
    1392: "файл или папка повреждены",
}
_ERRNO_TEXTS = {
    errno.EACCES: "нет доступа",
    errno.EPERM: "нет доступа",
    errno.ENOENT: "файл не найден",
    errno.ENOSPC: "на диске недостаточно места",
    errno.EROFS: "диск доступен только для чтения",
    errno.ENAMETOOLONG: "слишком длинное имя или путь",
    errno.EIO: "ошибка чтения или записи диска",
    errno.EBUSY: "файл занят другой программой",
}


def describe_error(error: BaseException) -> str:
    """Короткая понятная причина ошибки: «файл занят другой программой», «нет доступа»."""
    winerror = getattr(error, "winerror", None)
    if winerror in _WINERROR_TEXTS:
        return _WINERROR_TEXTS[winerror]
    code = getattr(error, "errno", None)
    if code in _ERRNO_TEXTS:
        return _ERRNO_TEXTS[code]
    return getattr(error, "strerror", None) or str(error) or type(error).__name__


def is_same_copy(info: os.stat_result, size: int, mtime: float) -> bool:
    """Копия совпадает с исходным файлом: тот же размер и время изменения (с допуском FAT)."""
    return info.st_size == size and abs(info.st_mtime - mtime) <= SAME_TIME_TOLERANCE


class ChangedOnlyPaths:
    """Постоянные пути копий одного задания для режима «только новые и измененные».

    Пути не зависят от того, что уже лежит в папке назначения, поэтому каждый запуск находит копии
    прошлого запуска. Совпадения имен внутри одного копирования получают номер по порядку источников,
    и номер тоже не меняется от запуска к запуску: две папки «Документы» — «Документы» и
    «Документы_(1)»; одинаковые имена файлов, которые попадают в одну папку, — «имя_(1).txt».
    Имена файлов из папок запоминаются, только если содержимое нескольких источников ложится в одну
    папку (claim_folder_files): иначе совпасть им не с чем, а память на миллион путей не тратится.
    """

    def __init__(self, root: str, limit: int, claim_folder_files: bool):
        self.root = root
        self.limit = limit
        self.claim_folder_files = claim_folder_files
        self._bases: Set[str] = set()
        self._claimed: Set[str] = set()

    def folder_base(self, name: str) -> str:
        """Папка копии выбранной папки."""
        base, counter = os.path.join(self.root, name), 0
        while os.path.normcase(base) in self._bases:
            counter += 1
            base = os.path.join(self.root, f"{name}_({counter})")
        self._bases.add(os.path.normcase(base))
        return base

    def target(self, directory: str, name: str, from_folder: bool) -> Tuple[Optional[str], bool]:
        """Путь копии файла и признак «имя укорочено»; None, если путь не уложить в лимит длины."""
        path, shortened = self._fit(directory, name)
        if path is None or (from_folder and not self.claim_folder_files):
            return path, shortened
        stem, ext = os.path.splitext(name)
        counter = 0
        while os.path.normcase(path) in self._claimed:
            counter += 1
            path, shortened = self._fit(directory, f"{stem}_({counter}){ext}")
            if path is None:
                return None, False
        self._claimed.add(os.path.normcase(path))
        return path, shortened

    def _fit(self, directory: str, name: str) -> Tuple[Optional[str], bool]:
        path = os.path.join(directory, name)
        if not self.limit or len(path) <= self.limit:
            return path, False
        # запас под дату, которую получит прежняя копия, если файл изменится
        short = safety.shorten_name(name, self.limit - len(directory) - 1 - safety.NAME_SUFFIX_RESERVE)
        if short is None:
            return None, False
        path = os.path.join(directory, short)
        return (path, True) if len(path) <= self.limit else (None, False)


class BackupRunner:
    """Выполняет одно копирование. Метод run() блокирующий, отмена через cancel() из другого потока."""

    PROGRESS_INTERVAL = 0.1

    def __init__(self, jobs: Iterable[BackupJob], options: Optional[BackupOptions] = None,
                 policy: Optional[safety.SafetyPolicy] = None,
                 on_progress: Optional[ProgressCallback] = None):
        self.jobs = list(jobs)
        self.options = options or BackupOptions()
        self.policy = policy if policy is not None else safety.SafetyPolicy.default()
        self.on_progress = on_progress
        self.result = BackupResult()
        self.total_files = 0
        self.total_size = 0
        self._job_totals: List[Tuple[int, int, int]] = []  # файлов к копированию, их объем, без изменений
        self._cancel = threading.Event()
        self._last_report = 0.0
        self._protected = safety.ProtectedPaths(self.policy.protected_paths)
        self._destinations = [safety.normalize(job.destination) for job in self.jobs if job.destination]
        self._blocked_dirs: List[str] = []
        self._reported_access: Set[str] = set()
        self._log_counts: Dict[str, int] = {}
        self._moment: Optional[datetime] = None  # начало копирования: дата в имени папки копии
        self._unchanged_total = 0  # «только новые и измененные»: неизмененные файлы по первому проходу
        self.log = get_logger()

    def cancel(self) -> None:
        self._cancel.set()

    def options_for(self, job: BackupJob) -> BackupOptions:
        """Параметры копирования задания: свои, если заданы, иначе общие."""
        return job.options or self.options

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ------------------------------------------------------------------ run
    def run(self) -> BackupResult:
        result = self.result
        self._moment = datetime.now()
        try:
            self._scan()
            result.total_bytes = self.total_size
            if self.cancelled:
                return self._finish(STATUS_CANCELLED, "Операция отменена")
            if self.total_files == 0:
                if self._unchanged_total:
                    result.unchanged_count = self._unchanged_total
                    return self._finish(STATUS_OK, self._no_changes_message())
                return self._finish(STATUS_FAILED, "Нет файлов для копирования" + self._skipped_suffix())

            self._status(f"Начинаем копирование ({self.total_size / MB:.1f} MB)")
            for job, totals in zip(self.jobs, self._job_totals):
                if self.cancelled:
                    break
                self._copy_job(job, totals)

            skipped = self._skipped_suffix()
            same = self._unchanged_suffix()
            if self.cancelled:
                return self._finish(STATUS_CANCELLED,
                                    f"Операция отменена (скопировано {count_files(result.copied_count)})")
            if result.errors and result.copied_count == 0 and not result.unchanged_count:
                return self._finish(STATUS_FAILED,
                                    f"Копирование не выполнено, ошибок: {len(result.errors)}{skipped}")
            if result.errors:
                return self._finish(STATUS_PARTIAL, f"Скопировано {count_files(result.copied_count)}{same}, "
                                                    f"ошибок: {len(result.errors)}{skipped}")
            if result.copied_count == 0 and result.unchanged_count:
                return self._finish(STATUS_OK, self._no_changes_message())
            tabs = f" из {count_tabs_genitive(len(self.jobs))}" if len(self.jobs) > 1 else ""
            return self._finish(STATUS_OK,
                                f"Успешно скопировано {count_files(result.copied_count)}{tabs}{same}{skipped}")
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

    def _unchanged_suffix(self) -> str:
        count = self.result.unchanged_count
        return f", без изменений: {count_files(count)}" if count else ""

    def _no_changes_message(self) -> str:
        return (f"Новых и измененных файлов нет, без изменений: {count_files(self.result.unchanged_count)}"
                f"{self._skipped_suffix()}")

    # ------------------------------------------------------------ проход 1
    def _scan(self) -> None:
        """Считает файлы и объем, записывает пропуски и ненайденные источники.

        В режиме «только новые и измененные» неизмененные файлы в счет не идут: объем, проверка места
        и процент хода считаются по тому, что действительно будет скопировано.
        """
        for job in self.jobs:
            count = size = unchanged = 0
            options = self.options_for(job)
            paths = self._changed_only_paths(job, options)
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
                    self._note(f"Выбранная папка является ссылкой, копируется ее содержимое: {folder}")
                base = self._folder_base(paths, folder, options) if paths is not None else ""
                for kind, path, relative, file_size, mtime in self._walk(folder, report=True,
                                                                         on_error=self._access_error):
                    if kind != "file":
                        continue
                    if paths is not None and self._has_same_copy(paths, os.path.join(base, relative) if relative
                                                                 else base, path, file_size, mtime, True):
                        unchanged += 1
                        continue
                    count += 1
                    size += file_size
            for path in job.files:
                if self.cancelled:
                    return
                state, text, file_size, mtime = self._file_state(path)
                if state == "missing":
                    self._error(text)
                elif state in ("skip", "limit"):
                    self._skip(text, over_limit=state == "limit")
                elif paths is not None and self._has_same_copy(paths, paths.root, path, file_size, mtime, False):
                    unchanged += 1
                else:
                    count += 1
                    size += file_size
            self._job_totals.append((count, size, unchanged))
            self.total_files += count
            self.total_size += size
            self._unchanged_total += unchanged

    def _job_root(self, job: BackupJob, options: BackupOptions) -> str:
        """Куда ложится копия задания: папка назначения или папка с датой внутри нее."""
        if options.create_backup_folder:
            return os.path.join(job.destination, backup_folder_name(self._moment))
        return job.destination

    def _changed_only_paths(self, job: BackupJob, options: BackupOptions) -> Optional[ChangedOnlyPaths]:
        # без папки назначения сравнивать не с чем: задание все равно не копируется
        if not options.copy_only_changed or not job.destination:
            return None
        merged = options.copy_folder_contents and len(job.folders) + len(job.files) > 1
        return ChangedOnlyPaths(self._job_root(job, options), self.policy.max_path_length, merged)

    @staticmethod
    def _folder_base(paths: ChangedOnlyPaths, folder: str, options: BackupOptions) -> str:
        return paths.root if options.copy_folder_contents else paths.folder_base(folder_copy_name(folder))

    @staticmethod
    def _has_same_copy(paths: ChangedOnlyPaths, directory: str, source: str, size: int, mtime: float,
                       from_folder: bool) -> bool:
        target, _shortened = paths.target(directory, os.path.basename(source), from_folder)
        if target is None:
            return False
        try:
            info = os.stat(target)
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and is_same_copy(info, size, mtime)

    def _folder_state(self, folder: str, job: BackupJob) -> Tuple[str, str]:
        if not os.path.isdir(folder):
            return "missing", f"Папка не найдена, пропущена: {folder}"
        if self._protected.contains(folder):
            return "skip", f"Системная папка не копируется: {folder}"
        if job.destination and safety.normalize(folder) == safety.normalize(job.destination):
            return "skip", f"Папка совпадает с папкой назначения и не копируется: {folder}"
        return "ok", ""

    def _file_state(self, path: str) -> Tuple[str, str, int, float]:
        """Состояние явно выбранного файла, его размер и время изменения."""
        if not os.path.exists(path):
            return "missing", f"Файл не найден, пропущен: {path}", 0, 0.0
        if self._protected.contains(path):
            return "skip", f"Системный файл не копируется: {path}", 0, 0.0
        try:
            info = os.stat(path)  # явно выбранный файл: ссылка разрешается
        except OSError as error:
            return "missing", f"Не удалось прочитать файл {path}: {describe_error(error)}", 0, 0.0
        if not stat.S_ISREG(info.st_mode):
            return "skip", f"Пропущен специальный файл: {path}", 0, 0.0
        if self.policy.max_file_size and info.st_size > self.policy.max_file_size:
            return "limit", f"Пропущен файл больше {self.policy.max_file_size_text}: {path}", 0, 0.0
        return "ok", "", info.st_size, info.st_mtime

    def _walk(self, folder: str, report: bool,
              on_error: Optional[Callable[[str, OSError], None]] = None) -> Iterator[WalkItem]:
        """Обходит папку по правилам безопасности. Сначала выдает папку, затем ее файлы."""
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
            yield "dir", current, relative, 0, 0.0
            parent = safety.normalize(current)
            subdirs = []
            for entry in entries:
                if self.cancelled:
                    return
                kind, size, mtime = self._classify(entry, parent, prune, report, on_error)
                if kind == "dir":
                    subdirs.append((entry.path, os.path.join(relative, entry.name) if relative else entry.name))
                elif kind == "file":
                    yield "file", entry.path, relative, size, mtime
            stack.extend(reversed(subdirs))

    def _classify(self, entry: os.DirEntry, parent: str, prune: List[str], report: bool,
                  on_error: Optional[Callable[[str, OSError], None]]) -> Tuple[Optional[str], int, float]:
        """Вид элемента («dir», «file» или None — пропустить), размер и время изменения файла."""
        path = entry.path
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as error:
            if on_error is not None:
                on_error(path, error)
            return None, 0, 0.0
        if safety.entry_is_link(entry, info):
            if report:
                self._skip(f"Пропущена ссылка (symlink или junction): {path}")
            return None, 0, 0.0
        if stat.S_ISDIR(info.st_mode):
            if self._protected.is_child(parent, path):
                if report:
                    self._skip(f"Пропущена системная папка: {path}")
                return None, 0, 0.0
            if any(safety.is_inside(path, root) for root in prune):
                if report:
                    self._skip(f"Пропущена папка назначения внутри копируемой папки: {path}")
                return None, 0, 0.0
            return "dir", 0, 0.0
        if self._protected.is_child(parent, path):
            if report:
                self._skip(f"Пропущен системный файл: {path}")
            return None, 0, 0.0
        if not stat.S_ISREG(info.st_mode):
            if report:
                self._skip(f"Пропущен специальный файл: {path}")
            return None, 0, 0.0
        if self.policy.max_file_size and info.st_size > self.policy.max_file_size:
            if report:
                self._skip(f"Пропущен файл больше {self.policy.max_file_size_text}: {path}", over_limit=True)
            return None, 0, 0.0
        return "file", info.st_size, info.st_mtime

    # ------------------------------------------------------------ проход 2
    def _copy_job(self, job: BackupJob, totals: Tuple[int, int, int]) -> None:
        count, size, unchanged = totals
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
            self.result.unchanged_count += unchanged  # все файлы вкладки уже есть в копии
            return
        try:
            os.makedirs(job.destination, exist_ok=True)
        except OSError as error:
            self._error(f"Не удалось создать папку назначения {job.destination}: {describe_error(error)}",
                        technical=error)
            return
        free = free_space(job.destination)
        if free is not None and free < size:
            self._error(f"Недостаточно свободного места в {job.destination} "
                        f"для вкладки '{job.name}' (нужно {size / MB:.1f} MB)")
            return

        options = self.options_for(job)
        destination = self._job_root(job, options)
        if options.create_backup_folder:
            try:
                os.makedirs(destination, exist_ok=True)
            except OSError as error:
                self._error(f"Не удалось создать папку {destination}: {describe_error(error)}", technical=error)
                return

        paths = self._changed_only_paths(job, options)
        for folder in job.folders:
            if self.cancelled:
                return
            state, _text = self._folder_state(folder, job)
            if state == "ok":
                self._copy_folder(folder, destination, job.destination, options, paths)
        for path in job.files:
            if self.cancelled:
                return
            state, _text, file_size, mtime = self._file_state(path)
            if state != "ok":
                continue
            if paths is not None:
                self._copy_if_changed(path, destination, file_size, mtime, job.destination, paths, False)
            else:
                self._copy_file(path, destination, file_size, job.destination, options.keep_history)

    def _copy_folder(self, folder: str, destination: str, destination_root: str, options: BackupOptions,
                     paths: Optional[ChangedOnlyPaths] = None) -> None:
        if paths is not None:
            base = self._folder_base(paths, folder, options)
        elif options.copy_folder_contents:
            base = destination
        else:
            base = safe_destination_path(os.path.join(destination, folder_copy_name(folder)),
                                         options.keep_history)
        for kind, path, relative, size, mtime in self._walk(folder, report=False, on_error=self._access_error):
            if self.cancelled:
                return
            if safety.has_parent_reference(relative):
                self._skip(f"Небезопасный относительный путь, пропущено: {path}")
                continue
            target_dir = os.path.join(base, relative) if relative else base
            if kind == "dir":
                self._make_dir(target_dir, path)
            elif paths is None:
                self._copy_file(path, target_dir, size, destination_root, options.keep_history)
            elif self._is_blocked(target_dir):
                self._skip(f"Файл в пропущенной папке: {path}", log=False)
            else:
                self._copy_if_changed(path, target_dir, size, mtime, destination_root, paths, True)

    def _make_dir(self, target_dir: str, source_dir: str) -> None:
        if self._is_blocked(target_dir):
            return
        limit = self.policy.max_path_length
        if limit and len(target_dir) > limit:
            self._blocked_dirs.append(target_dir)
            self._skip(f"Путь папки в копии длиннее {limit} символов, папка пропущена: {source_dir}", over_limit=True)
            return
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as error:
            self._blocked_dirs.append(target_dir)
            self._error(f"Не удалось создать папку {target_dir}: {describe_error(error)}", technical=error)

    def _is_blocked(self, path: str) -> bool:
        return any(path == blocked or path.startswith(blocked + os.sep) for blocked in self._blocked_dirs)

    def _copy_file(self, source: str, target_dir: str, size: int, destination_root: str,
                   keep_history: bool) -> None:
        if self._is_blocked(target_dir):
            self._skip(f"Файл в пропущенной папке: {source}", log=False)
            return
        target, shortened = self._target_path(target_dir, os.path.basename(source), keep_history)
        if target is None:
            self._skip(f"Путь копии длиннее {self.policy.max_path_length} символов, файл пропущен: {source}",
                       over_limit=True)
            return
        if not safety.is_inside(target, destination_root):
            self._skip(f"Путь копии выходит за пределы папки назначения, файл пропущен: {source}")
            return
        self._copy_to(source, target, size, shortened)

    def _copy_if_changed(self, source: str, target_dir: str, size: int, mtime: float, destination_root: str,
                         paths: ChangedOnlyPaths, from_folder: bool) -> None:
        """«Только новые и измененные»: файл с той же копией пропускается. У измененного файла прежняя
        копия переименовывается (к имени добавляется дата ее изменения), новая ложится на ее место."""
        target, shortened = paths.target(target_dir, os.path.basename(source), from_folder)
        if target is None:
            self._skip(f"Путь копии длиннее {self.policy.max_path_length} символов, файл пропущен: {source}",
                       over_limit=True)
            return
        if not safety.is_inside(target, destination_root):
            self._skip(f"Путь копии выходит за пределы папки назначения, файл пропущен: {source}")
            return
        try:
            info: Optional[os.stat_result] = os.stat(target)
        except FileNotFoundError:
            info = None
        except OSError as error:
            self._error(f"Не скопирован {source}: {describe_error(error)}", technical=error)
            return
        if info is not None:
            if not stat.S_ISREG(info.st_mode):
                what = "папка" if stat.S_ISDIR(info.st_mode) else "другой объект"
                self._error(f"Не скопирован {source}: на месте копии уже есть {what} с таким же именем: {target}")
                return
            if is_same_copy(info, size, mtime):
                self.result.unchanged_count += 1
                return
            version = self._version_path(target, info.st_mtime)
            if version is None:
                self._skip(f"Путь прежней копии длиннее {self.policy.max_path_length} символов, "
                           f"измененный файл пропущен: {source}", over_limit=True)
                return
            try:
                os.rename(target, version)
            except OSError as error:
                self._error(f"Не скопирован {source}: не удалось сохранить прежнюю копию: {describe_error(error)}",
                            technical=error)
                return
            self._note(f"Файл изменился, прежняя копия сохранена как {os.path.basename(version)}: {target}")
        self._copy_to(source, target, size, shortened)

    def _version_path(self, target: str, moment: float) -> Optional[str]:
        """Свободное имя для прежней копии: имя_дд.мм.гггг_чч-мм-сс по времени ее изменения.

        None, если имя с датой не уложить в лимит длины пути даже укороченным.
        """
        try:
            stamp = datetime.fromtimestamp(moment).strftime(COPY_STAMP_FORMAT)
        except (OverflowError, OSError, ValueError):
            stamp = (self._moment or datetime.now()).strftime(COPY_STAMP_FORMAT)
        directory, name = os.path.split(target)
        stem, ext = os.path.splitext(name)
        limit = self.policy.max_path_length
        for counter in range(VERSION_ATTEMPTS):
            candidate = f"{stem}_{stamp}_({counter}){ext}" if counter else f"{stem}_{stamp}{ext}"
            path = os.path.join(directory, candidate)
            if limit and len(path) > limit:
                short = safety.shorten_name(candidate, limit - len(directory) - 1)
                if short is None:
                    return None
                path = os.path.join(directory, short)
            if not os.path.lexists(path):
                return path
        return None

    def _copy_to(self, source: str, target: str, size: int, shortened: bool) -> None:
        try:
            shutil.copy2(source, target)
        except Exception as error:
            self._error(f"Не скопирован {source}: {describe_error(error)}", technical=error)
            return
        if shortened:
            self._note(f"Имя файла укорочено до {len(os.path.basename(target))} символов: "
                       f"{source} -> {os.path.basename(target)}")
        self.result.copied_bytes += size
        self.result.copied_count += 1
        self._report_progress()

    def _target_path(self, directory: str, name: str, keep_history: bool) -> Tuple[Optional[str], bool]:
        """Путь копии с учетом совпадения имен и лимита длины пути."""
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
        self._error(f"Не удалось прочитать {path}: {describe_error(error)}", security=True, technical=error)

    def _error(self, text: str, security: bool = False, technical: Optional[BaseException] = None) -> None:
        """Ошибка в результат и в журнал. Технический текст ошибки пишется только в журнал."""
        self.result.errors.append(text)
        message = f"{safety.SECURITY_TAG} {text}" if security else text
        if technical is not None:
            message += f" ({technical})"
        self._log_limited("ошибка", logging.ERROR, message)

    def _skip(self, text: str, log: bool = True, over_limit: bool = False) -> None:
        self.result.skipped.append(text)
        if over_limit:
            self.result.over_limit.append(text)
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
