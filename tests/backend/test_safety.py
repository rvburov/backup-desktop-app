"""Раздел «Безопасность и защита данных»: каждое правило проверяется на настоящих файлах."""
import os
import subprocess
import sys

import pytest

from backup_app.backend import copier as copier_module
from backup_app.backend import safety
from backup_app.backend.copier import STATUS_OK, BackupJob, BackupOptions, BackupRunner
from backup_app.backend.safety import ProtectedPaths, SafetyPolicy, shorten_name
from helpers import list_rel, make_tree

windows_only = pytest.mark.skipif(os.name != "nt", reason="junction есть только в Windows")
posix_only = pytest.mark.skipif(os.name == "nt", reason="специальные файлы есть только в Linux и macOS")


def make_junction(link, target):
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return result.returncode == 0


def make_symlink(link, target, directory=False):
    try:
        os.symlink(str(target), str(link), target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("нет прав на создание символьных ссылок")


def run(jobs, policy=None, options=None):
    runner = BackupRunner(jobs, options or BackupOptions(False, True, False), policy or SafetyPolicy())
    return runner.run()


@pytest.fixture
def area(tmp_path):
    src = tmp_path / "src"
    outside = tmp_path / "outside"
    dst = tmp_path / "dst"
    make_tree(src, {"docs": {"normal.txt": "n"}})
    make_tree(outside, {"secret.txt": "s"})
    dst.mkdir()
    return src, outside, dst


def security_lines(records):
    return [line for line in records if line.startswith(safety.SECURITY_TAG)]


# ------------------------------------------------------------------ ссылки
@windows_only
def test_junction_inside_folder_is_skipped_and_logged(area, log_records):
    src, outside, dst = area
    assert make_junction(src / "docs" / "to_outside", outside)
    assert make_junction(src / "docs" / "loop", src / "docs")
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))])
    assert list_rel(dst) == ["docs/normal.txt"]
    assert result.status == STATUS_OK and len(result.skipped) == 2
    assert result.over_limit == []
    assert "пропущено по правилам безопасности: 2" in result.message
    assert sum("Пропущена ссылка" in line for line in security_lines(log_records)) == 2


def test_symlinks_inside_folder_are_skipped(area):
    src, outside, dst = area
    make_symlink(src / "docs" / "file_link.txt", outside / "secret.txt")
    make_symlink(src / "docs" / "dir_link", outside, directory=True)
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))])
    assert list_rel(dst) == ["docs/normal.txt"]
    assert len(result.skipped) == 2 and result.over_limit == []


class OldDirEntry:
    """DirEntry из Python 3.11: метода is_junction у него еще нет."""

    def __init__(self, entry):
        self._entry = entry

    def is_symlink(self):
        return self._entry.is_symlink()


def test_link_check_works_without_dir_entry_is_junction(area):
    src, outside, dst = area
    expected = {"docs": False}
    if os.name == "nt":
        assert make_junction(src / "link", outside)
        expected["link"] = True
    with os.scandir(str(src)) as entries:
        found = {entry.name: safety.entry_is_link(OldDirEntry(entry), entry.stat(follow_symlinks=False))
                 for entry in entries}
    assert found == expected


@windows_only
def test_explicitly_selected_junction_is_copied(area, log_records):
    src, outside, dst = area
    link = src / "selected_link"
    assert make_junction(link, outside)
    result = run([BackupJob("x", [str(link)], [], str(dst))])
    assert list_rel(dst) == ["selected_link/secret.txt"]
    assert result.status == STATUS_OK
    assert any("является ссылкой" in line for line in security_lines(log_records))


# ------------------------------------------------------- системные пути
def test_protected_folder_inside_source_is_skipped(area):
    src, _outside, dst = area
    make_tree(src / "docs" / "System", {"kernel.bin": "k"})
    policy = SafetyPolicy(protected_paths=(str(src / "docs" / "System"),))
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))], policy)
    assert list_rel(dst) == ["docs/normal.txt"]
    assert any("системная папка" in text for text in result.skipped)


def test_protected_folder_cannot_be_source(area):
    src, _outside, dst = area
    policy = SafetyPolicy(protected_paths=(str(src),))
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))], policy)
    assert list_rel(dst) == []
    assert any("Системная папка не копируется" in text for text in result.skipped)


def test_protected_destination_is_an_error(area, log_records):
    src, _outside, dst = area
    policy = SafetyPolicy(protected_paths=(str(dst),))
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))], policy)
    assert list_rel(dst) == []
    assert any("Папка назначения находится в системной папке" in error for error in result.errors)
    assert any("Папка назначения находится в системной папке" in line for line in security_lines(log_records))


def test_real_system_paths_are_known():
    paths = safety.system_paths()
    assert paths
    if os.name == "nt":
        windows = safety.normalize(os.environ.get("SystemRoot", "C:" + chr(92) + "Windows"))
        assert windows in paths
    else:
        assert safety.normalize("/etc") in paths


@windows_only
def test_recycle_bin_on_any_drive_is_protected():
    protected = ProtectedPaths([])
    assert protected.contains("D:" + chr(92) + "$Recycle.Bin" + chr(92) + "x")
    assert protected.contains("E:" + chr(92) + "System Volume Information")
    assert protected.is_child("d:" + chr(92), "D:" + chr(92) + "pagefile.sys")
    assert not protected.contains("D:" + chr(92) + "Work" + chr(92) + "$Recycle.Bin")


# ---------------------------------------------- папка назначения в источнике
def test_destination_inside_source_is_not_copied_into_itself(tmp_path):
    src = tmp_path / "profile"
    make_tree(src, {"doc.txt": "d"})
    dst = src / "Backups"
    dst.mkdir()
    job = BackupJob("x", [str(src)], [], str(dst))
    for _ in range(2):
        run([job], options=BackupOptions(False, False, False))
    files = list_rel(dst)
    assert files == ["profile/doc.txt", "profile_(1)/doc.txt"]


def test_destination_equal_to_source_is_skipped(tmp_path):
    folder = tmp_path / "same"
    make_tree(folder, {"doc.txt": "d"})
    result = run([BackupJob("x", [str(folder)], [], str(folder))])
    assert list_rel(folder) == ["doc.txt"]
    assert any("совпадает с папкой назначения" in text for text in result.skipped)


# ------------------------------------------------------ типы и размер файлов
@posix_only
def test_named_pipe_is_skipped(area):
    src, _outside, dst = area
    os.mkfifo(str(src / "docs" / "pipe"))
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))])
    assert list_rel(dst) == ["docs/normal.txt"]
    assert any("специальный файл" in text for text in result.skipped)


def test_files_over_size_limit_are_skipped(area):
    src, _outside, dst = area
    make_tree(src / "docs", {"big.bin": "x" * 100})
    (src / "big_single.bin").write_text("y" * 100)
    policy = SafetyPolicy(max_file_size=10)
    result = run([BackupJob("x", [str(src / "docs")], [str(src / "big_single.bin")], str(dst))], policy)
    assert list_rel(dst) == ["docs/normal.txt"]
    assert len(result.skipped) == 2 and all("больше" in text for text in result.skipped)
    assert result.over_limit == result.skipped


def test_zero_size_limit_means_unlimited(area):
    src, _outside, dst = area
    make_tree(src / "docs", {"big.bin": "x" * 100})
    result = run([BackupJob("x", [str(src / "docs")], [], str(dst))], SafetyPolicy(max_file_size=0))
    assert sorted(list_rel(dst)) == ["docs/big.bin", "docs/normal.txt"] and not result.skipped


def test_default_policy_uses_two_gigabytes():
    assert SafetyPolicy().max_file_size == 2 * 1024 ** 3
    assert SafetyPolicy.default(5).max_file_size == 5 * 1024 ** 3
    assert SafetyPolicy.default().protected_paths == tuple(safety.system_paths())


# -------------------------------------------------------------- длина пути
def test_long_file_name_is_shortened(tmp_path, log_records):
    src = tmp_path / "s"
    long_name = "очень_длинное_имя_файла_" * 4 + ".txt"
    make_tree(src, {long_name: "data"})
    dst = tmp_path / "d"
    dst.mkdir()
    limit = len(str(dst)) + 90
    result = run([BackupJob("x", [], [str(src / long_name)], str(dst))], SafetyPolicy(max_path_length=limit))
    copied = list_rel(dst)
    assert result.status == STATUS_OK and len(copied) == 1
    assert copied[0].endswith(".txt") and "~" in copied[0]
    assert len(os.path.join(str(dst), copied[0])) <= limit
    assert any("Имя файла укорочено" in line for line in security_lines(log_records))


def test_too_deep_folder_is_skipped(tmp_path):
    src = tmp_path / "s"
    make_tree(src, {"a.txt": "1", "level_one_folder": {"level_two_folder": {"deep.txt": "2"}}})
    dst = tmp_path / "d"
    dst.mkdir()
    limit = len(str(dst)) + len("/s/level_one_folder") + 5
    result = run([BackupJob("x", [str(src)], [], str(dst))], SafetyPolicy(max_path_length=limit))
    copied = list_rel(dst)
    assert "s/a.txt" in copied and not any("deep.txt" in path for path in copied)
    assert any("длиннее" in text for text in result.over_limit)


def test_shorten_name():
    name = "x" * 100 + ".docx"
    short = shorten_name(name, 40)
    assert len(short) == 40 and short.endswith(".docx") and "~" in short
    assert shorten_name("y" * 100 + ".docx", 40) != short
    assert shorten_name("short.txt", 40) == "short.txt"
    assert shorten_name(name, 10) is None


# ------------------------------------------------------ выход за пределы
def test_copy_outside_destination_is_blocked(area, monkeypatch):
    src, _outside, dst = area
    monkeypatch.setattr(copier_module.safety, "is_inside", lambda path, root: False)
    result = run([BackupJob("x", [], [str(src / "docs" / "normal.txt")], str(dst))])
    assert list_rel(dst) == []
    assert any("за пределы папки назначения" in text for text in result.skipped)


def test_parent_reference_detection():
    assert safety.has_parent_reference("../x")
    assert safety.has_parent_reference("a" + chr(92) + ".." + chr(92) + "b")
    assert safety.has_parent_reference(os.path.abspath("x"))
    assert not safety.has_parent_reference("a/b..c/d")


def test_is_inside():
    base = os.path.abspath("base")
    assert safety.is_inside(os.path.join(base, "child"), base)
    assert safety.is_inside(base, base)
    assert not safety.is_inside(base + "_other", base)
    if sys.platform == "win32":
        assert safety.is_inside(os.path.join(base.upper(), "x"), base.lower())


# ------------------------------------------------------- журнал [SECURITY]
def test_log_is_limited_but_counts_are_complete(tmp_path, monkeypatch, log_records):
    monkeypatch.setattr(copier_module, "LOG_LIMIT", 3)
    src = tmp_path / "s"
    make_tree(src, {f"big{i}.bin": "x" * 20 for i in range(10)})
    make_tree(src, {"ok.txt": "1"})
    dst = tmp_path / "d"
    dst.mkdir()
    result = run([BackupJob("x", [str(src)], [], str(dst))], SafetyPolicy(max_file_size=5))
    assert len(result.skipped) == 10
    skip_lines = [line for line in security_lines(log_records) if "больше" in line]
    assert len(skip_lines) == 3
    assert any("Слишком много записей" in line for line in log_records)
    assert any("Всего записей вида «пропуск»: 10" in line for line in log_records)
