import os
import time
from datetime import datetime

import pytest

from backup_app.backend import copier as copier_module
from backup_app.backend.constants import BACKUP_FOLDER_PREFIX
from backup_app.backend.copier import (STATUS_CANCELLED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL,
                                       BackupJob, BackupOptions, BackupRunner, folder_copy_name,
                                       safe_destination_path)
from backup_app.backend.safety import SafetyPolicy
from helpers import list_rel, make_tree

SRC = {"docs": {"a.txt": "A", "sub": {"b.txt": "BB"}}, "single.txt": "S"}


def run(jobs, options=None, policy=None, on_progress=None):
    """Выполняет копирование в текущем потоке и возвращает (строки прогресса, результат)."""
    lines = []

    def progress(percent, text):
        lines.append(text)
        if on_progress is not None:
            on_progress(runner, text)

    runner = BackupRunner(jobs, options or BackupOptions(), policy or SafetyPolicy(), on_progress=progress)
    result = runner.run()
    return lines, result


def daily_folder():
    return f"{BACKUP_FOLDER_PREFIX} {datetime.now():%d-%m-%Y}"


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    make_tree(src, SRC)
    dst = tmp_path / "dst"
    dst.mkdir()
    return str(src), str(dst)


def job_for(src, dst, folders=("docs",), files=("single.txt",), name="Вкладка"):
    return BackupJob(name=name, folders=[os.path.join(src, f) for f in folders],
                     files=[os.path.join(src, f) for f in files], destination=dst)


def test_whole_folder_copy_into_daily_folder(tree):
    src, dst = tree
    _lines, result = run([job_for(src, dst)], BackupOptions(False, True, True))
    day = daily_folder()
    assert list_rel(dst) == sorted([f"{day}/docs/a.txt", f"{day}/docs/sub/b.txt", f"{day}/single.txt"])
    assert result.status == STATUS_OK
    assert result.copied_count == 3
    assert result.message == "Успешно скопировано 3 файлов"
    assert result.total_bytes == 4 and result.copied_bytes == 4
    assert result.errors == [] and result.skipped == []


def test_second_run_same_day_adds_timestamped_copies(tree):
    src, dst = tree
    for _ in range(2):
        run([job_for(src, dst)], BackupOptions(False, True, True))
    files = list_rel(dst)
    assert len(files) == 6
    assert any("/docs_" in f for f in files) and any("/single_" in f for f in files)


def test_counter_suffix_when_history_disabled(tree):
    src, dst = tree
    for _ in range(2):
        run([job_for(src, dst)], BackupOptions(False, False, False))
    files = list_rel(dst)
    assert "docs_(1)/a.txt" in files and "single_(1).txt" in files


def test_contents_mode_copies_into_destination_root(tree):
    src, dst = tree
    _lines, result = run([job_for(src, dst, files=())], BackupOptions(True, True, False))
    assert list_rel(dst) == ["a.txt", "sub/b.txt"]
    assert result.success


def test_empty_subfolders_and_empty_files_are_copied(tmp_path):
    src = tmp_path / "src"
    make_tree(src, {"docs": {"empty.txt": "", "nested": {"deeper": {}}}})
    dst = tmp_path / "dst"
    dst.mkdir()
    _lines, result = run([BackupJob("x", [str(src / "docs")], [], str(dst))], BackupOptions(False, True, False))
    assert result.status == STATUS_OK and result.copied_count == 1
    assert os.path.isdir(dst / "docs" / "nested" / "deeper")
    assert list_rel(dst) == ["docs/empty.txt"]


def test_no_sources_at_all_fails(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    job = BackupJob("x", [str(tmp_path / "nope")], [str(tmp_path / "nope.txt")], str(dst))
    _lines, result = run([job])
    assert result.status == STATUS_FAILED
    assert result.message.startswith("Нет файлов для копирования")
    assert any("не найдена" in error for error in result.errors)
    assert any("не найден" in error for error in result.errors)


def test_locked_file_does_not_abort_the_folder(tree, monkeypatch):
    src, dst = tree
    make_tree(os.path.join(src, "docs"), {"0_first.txt": "1", "locked.txt": "L", "z_last.txt": "Z"})
    real_copy2 = copier_module.shutil.copy2

    def failing_copy2(source, target):
        if os.path.basename(source) == "locked.txt":
            raise PermissionError(13, "Процесс не может получить доступ к файлу", source)
        return real_copy2(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", failing_copy2)
    _lines, result = run([job_for(src, dst)], BackupOptions(False, True, False))
    files = list_rel(dst)
    assert "docs/z_last.txt" in files and "docs/0_first.txt" in files and "single.txt" in files
    assert "docs/locked.txt" not in files
    assert result.status == STATUS_PARTIAL
    assert len(result.errors) == 1 and "locked.txt" in result.errors[0]
    assert result.message == "Скопировано 5 файлов, ошибок: 1"


def test_missing_source_folder_is_reported(tree):
    src, dst = tree
    job = job_for(src, dst, folders=("docs", "missing"), files=())
    _lines, result = run([job], BackupOptions(False, True, False))
    assert result.status == STATUS_PARTIAL
    assert any("не найдена" in error for error in result.errors)
    assert result.copied_count == 2


def test_cancel_reports_cancelled_status(tmp_path, monkeypatch):
    src = tmp_path / "src"
    make_tree(src, {"docs": {f"f{i:02d}.txt": "x" for i in range(10)}})
    dst = tmp_path / "dst"
    dst.mkdir()
    real_copy2 = copier_module.shutil.copy2

    def slow_copy2(source, target):
        time.sleep(0.02)
        return real_copy2(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", slow_copy2)
    monkeypatch.setattr(BackupRunner, "PROGRESS_INTERVAL", 0)

    def cancel_after_two(runner, text):
        if text.startswith("Копирование...") and text.endswith("Файлов: 2"):
            runner.cancel()

    _lines, result = run([BackupJob("x", [str(src / "docs")], [], str(dst))],
                         BackupOptions(False, True, False), on_progress=cancel_after_two)
    assert result.status == STATUS_CANCELLED
    assert "отменена" in result.message
    assert 0 < len(list_rel(dst)) < 10


def test_multiple_jobs_use_their_own_destinations(tmp_path):
    s1, s2, d1, d2 = (tmp_path / name for name in ("s1", "s2", "d1", "d2"))
    make_tree(s1, {"x.txt": "1"})
    make_tree(s2, {"y.txt": "22"})
    d1.mkdir()
    d2.mkdir()
    jobs = [BackupJob("T1", [], [str(s1 / "x.txt")], str(d1)), BackupJob("T2", [str(s2)], [], str(d2))]
    lines, result = run(jobs, BackupOptions(False, True, False))
    assert list_rel(d1) == ["x.txt"] and list_rel(d2) == ["s2/y.txt"]
    assert result.message == "Успешно скопировано 2 файлов из 2 вкладок"
    assert any("Копирование вкладки 'T2'" in line for line in lines)


def test_job_without_destination_is_an_error(tree):
    src, dst = tree
    jobs = [BackupJob("Пустая", [os.path.join(src, "docs")], [], ""), job_for(src, dst)]
    _lines, result = run(jobs, BackupOptions(False, True, False))
    assert result.status == STATUS_PARTIAL
    assert any("не выбрана папка назначения" in error for error in result.errors)


def test_insufficient_disk_space(tree, monkeypatch):
    src, dst = tree
    monkeypatch.setattr(copier_module, "free_space", lambda path: 0)
    _lines, result = run([job_for(src, dst)])
    assert result.status == STATUS_FAILED
    assert any("Недостаточно свободного места" in error for error in result.errors)
    assert list_rel(dst) == []


def test_progress_is_throttled(tmp_path):
    src = tmp_path / "src"
    make_tree(src, {"docs": {f"f{i:03d}.txt": "x" for i in range(300)}})
    dst = tmp_path / "dst"
    dst.mkdir()
    lines, result = run([BackupJob("x", [str(src / "docs")], [], str(dst))], BackupOptions(False, True, False))
    progress_lines = [line for line in lines if line.startswith("Копирование...")]
    assert result.copied_count == 300
    assert len(progress_lines) < 60
    assert progress_lines[-1].endswith("Файлов: 300")


def test_totals_are_counted_before_copying(tree):
    src, dst = tree
    runner = BackupRunner([job_for(src, dst)], BackupOptions(), SafetyPolicy())
    runner.run()
    assert runner.total_files == 3 and runner.total_size == 4


def test_safe_destination_path_falls_back_to_counter_on_same_second(tmp_path, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 6, 12, 0, 0)

    monkeypatch.setattr(copier_module, "datetime", FixedDateTime)
    original = tmp_path / "f.txt"
    original.write_text("1")
    stamped = safe_destination_path(str(original), keep_history=True)
    assert stamped.endswith("f_06.10.2026_12-00-00.txt")
    open(stamped, "w").close()
    assert safe_destination_path(str(original), keep_history=True).endswith("f_06.10.2026_12-00-00_(1).txt")
    assert safe_destination_path(str(original), keep_history=False).endswith("f_(1).txt")


def test_folder_copy_name():
    assert folder_copy_name("C:" + chr(92)) == "Диск_C"
    assert folder_copy_name("C:" + chr(92) + "Users" + chr(92) + "x" + chr(92)) == "x"
    assert folder_copy_name("/home/user/docs") == "docs"
