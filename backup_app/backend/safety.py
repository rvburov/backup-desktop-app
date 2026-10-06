"""Правила безопасности копирования. Без Qt.

Реализует раздел «Безопасность и защита данных» руководства пользователя:
- ссылки (symlink и junction) внутри выбранных папок не копируются;
- системные папки и файлы не копируются и не могут быть папкой назначения;
- копируются только обычные файлы и папки, специальные файлы пропускаются;
- файлы больше лимита пропускаются, по умолчанию лимит 2 ГБ;
- путь копии не длиннее 240 символов, длинные имена файлов укорачиваются;
- копия не может оказаться за пределами папки назначения.
Каждое такое событие записывается в журнал с меткой [SECURITY].
"""
import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

SECURITY_TAG = "[SECURITY]"

MAX_PATH_LENGTH = 240
DEFAULT_MAX_FILE_SIZE_GB = 2
GB = 1024 ** 3

# Запас длины пути под суффикс «_дд.мм.гггг_чч-мм-сс_(N)», который добавляется при совпадении имён.
NAME_SUFFIX_RESERVE = 26
# Самое короткое имя файла, до которого допускается укорачивание.
MIN_NAME_LENGTH = 24
MAX_EXTENSION_LENGTH = 10

# Имена в корне любого диска Windows, которые являются системными.
WINDOWS_ROOT_NAMES = frozenset({
    "$recycle.bin", "system volume information", "pagefile.sys", "hiberfil.sys", "swapfile.sys",
})


def normalize(path: str) -> str:
    """Абсолютный путь в единой форме для сравнения (на Windows без учёта регистра)."""
    return os.path.normcase(os.path.abspath(path))


def is_inside(path: str, root: str) -> bool:
    """True, если path совпадает с root или лежит внутри него."""
    path_norm, root_norm = normalize(path), normalize(root)
    if path_norm == root_norm:
        return True
    return path_norm.startswith(root_norm.rstrip("\\/") + os.sep)


def is_junction(path: str) -> bool:
    checker = getattr(os.path, "isjunction", None)
    if checker is not None:
        return checker(path)
    if os.name != "nt":
        return False
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return getattr(info, "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT


def is_link(path: str) -> bool:
    """Символьная ссылка или junction."""
    return os.path.islink(path) or is_junction(path)


def entry_is_link(entry: os.DirEntry, info: os.stat_result) -> bool:
    """То же для элемента os.scandir без лишних обращений к диску."""
    if entry.is_symlink():
        return True
    checker = getattr(entry, "is_junction", None)
    if checker is not None:
        try:
            return checker()
        except OSError:
            return False
    if os.name != "nt":
        return False
    return getattr(info, "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT


def has_parent_reference(relative: str) -> bool:
    """True, если относительный путь содержит переход «..» или является абсолютным."""
    if os.path.isabs(relative):
        return True
    return ".." in relative.replace("\\", "/").split("/")


def system_paths() -> List[str]:
    """Системные папки и файлы текущей ОС, которые нельзя копировать и выбирать назначением."""
    if os.name == "nt":
        env = os.environ
        drive = (env.get("SystemDrive") or "C:").rstrip("\\/") + "\\"
        candidates = [
            env.get("SystemRoot") or env.get("WINDIR") or os.path.join(drive, "Windows"),
            env.get("ProgramFiles") or os.path.join(drive, "Program Files"),
            env.get("ProgramFiles(x86)") or os.path.join(drive, "Program Files (x86)"),
            env.get("ProgramW6432"),
            os.path.join(drive, "Recovery"),
        ]
    elif sys.platform == "darwin":
        candidates = ["/System", "/bin", "/sbin", "/usr", "/dev", "/etc", "/private/etc", "/cores"]
    else:
        candidates = ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32",
                      "/proc", "/sbin", "/sys", "/usr"]
    result: List[str] = []
    for candidate in candidates:
        if candidate:
            normalized = normalize(candidate)
            if normalized not in result:
                result.append(normalized)
    return result


def _is_drive_root(normalized: str) -> bool:
    drive, rest = os.path.splitdrive(normalized)
    return bool(drive) and rest in ("\\", "/")


class ProtectedPaths:
    """Системные пути и быстрая проверка элементов при обходе папок."""

    def __init__(self, paths: Iterable[str], root_names: Optional[Iterable[str]] = None):
        self.paths: Tuple[str, ...] = tuple(normalize(path) for path in paths)
        self._exact = set(self.paths)
        self._parents = {os.path.dirname(path) for path in self.paths}
        if root_names is None:
            root_names = WINDOWS_ROOT_NAMES if os.name == "nt" else ()
        self.root_names = frozenset(name.lower() for name in root_names)

    def contains(self, path: str) -> Optional[str]:
        """Системный путь, которому принадлежит path, или None."""
        normalized = normalize(path)
        for root in self.paths:
            if normalized == root or normalized.startswith(root.rstrip("\\/") + os.sep):
                return root
        if self.root_names:
            drive, rest = os.path.splitdrive(normalized)
            first = rest.lstrip("\\/").split(os.sep, 1)[0]
            if drive and first.lower() in self.root_names:
                return os.path.join(drive + os.sep, first)
        return None

    def is_child(self, parent_normalized: str, path: str) -> bool:
        """Проверка элемента папки при обходе: всё, что глубже системных путей, отсекается раньше."""
        if parent_normalized in self._parents and normalize(path) in self._exact:
            return True
        if self.root_names and _is_drive_root(parent_normalized):
            return os.path.basename(path).lower() in self.root_names
        return False


@dataclass(frozen=True)
class SafetyPolicy:
    """Настройки правил безопасности для одного копирования."""

    max_path_length: int = MAX_PATH_LENGTH
    max_file_size: int = DEFAULT_MAX_FILE_SIZE_GB * GB  # 0 = без ограничения
    protected_paths: Tuple[str, ...] = ()

    @classmethod
    def default(cls, max_file_size_gb: int = DEFAULT_MAX_FILE_SIZE_GB) -> "SafetyPolicy":
        return cls(max_file_size=max(0, int(max_file_size_gb)) * GB, protected_paths=tuple(system_paths()))

    @property
    def max_file_size_text(self) -> str:
        gigabytes = self.max_file_size / GB
        return f"{gigabytes:g} ГБ"


def shorten_name(name: str, limit: int) -> Optional[str]:
    """Укорачивает имя файла до limit символов: сохраняет расширение и добавляет хэш для уникальности."""
    if len(name) <= limit:
        return name
    if limit < MIN_NAME_LENGTH:
        return None
    stem, extension = os.path.splitext(name)
    if len(extension) > MAX_EXTENSION_LENGTH:
        stem, extension = name, ""
    digest = hashlib.sha1(name.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    keep = limit - len(extension) - len(digest) - 1
    return f"{stem[:keep]}~{digest}{extension}"


def source_problem(path: str, protected: ProtectedPaths) -> Optional[str]:
    """Причина, по которой путь нельзя добавить в источники, или None."""
    if protected.contains(path):
        return f"Системная папка не может быть источником копирования: {path}"
    return None


def destination_problem(path: str, protected: ProtectedPaths) -> Optional[str]:
    """Причина, по которой путь нельзя выбрать папкой назначения, или None."""
    if protected.contains(path):
        return f"Системная папка не может быть папкой назначения: {path}"
    return None


def path_problem(path: str, protected: ProtectedPaths) -> Optional[str]:
    """Подсказка для пути в списке источников: недоступен или системный."""
    if not os.path.exists(path):
        return "Путь сейчас недоступен (диск не подключён или путь удалён). Будет пропущен при копировании."
    if protected.contains(path):
        return "Системный путь: будет пропущен при копировании."
    return None
