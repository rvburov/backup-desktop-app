import errno
import os
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from backup_app.backend import copier as copier_module
from backup_app.backend.constants import BACKUP_FOLDER_PREFIX, COPY_STAMP_FORMAT
from backup_app.backend.copier import (STATUS_CANCELLED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL,
                                       BackupJob, BackupOptions, BackupRunner, ChangedOnlyPaths, backup_folder_name,
                                       describe_error, folder_copy_name, safe_destination_path)
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
    assert result.message == "Успешно скопировано 3 файла"
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
    assert len(result.errors) == 1 and result.errors[0].endswith("locked.txt: нет доступа")
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
    assert result.message == "Успешно скопировано 2 файла из 2 вкладок"
    assert any("Копирование вкладки 'T2'" in line for line in lines)


def test_each_job_uses_its_own_options(tmp_path):
    s1, s2, d1, d2 = (tmp_path / name for name in ("s1", "s2", "d1", "d2"))
    make_tree(s1, {"x.txt": "1", "sub": {"y.txt": "2"}})
    make_tree(s2, {"z.txt": "3"})
    d1.mkdir()
    d2.mkdir()
    (d1 / "x.txt").write_text("старая копия")
    jobs = [
        BackupJob("Содержимое", [str(s1)], [], str(d1),
                  BackupOptions(copy_folder_contents=True, keep_history=False, create_backup_folder=False)),
        BackupJob("Папка дня", [str(s2)], [], str(d2)),  # без своих параметров: общие параметры runner
    ]
    _lines, result = run(jobs, BackupOptions(copy_folder_contents=False, keep_history=True, create_backup_folder=True))
    assert result.status == STATUS_OK
    assert list_rel(d1) == ["sub/y.txt", "x.txt", "x_(1).txt"]
    assert list_rel(d2) == [f"{daily_folder()}/s2/z.txt"]


def test_job_options_fall_back_to_runner_options():
    job = BackupJob("x")
    runner = BackupRunner([job], BackupOptions(True, False, False))
    assert runner.options_for(job) == BackupOptions(True, False, False)
    own = BackupOptions(False, True, True)
    assert runner.options_for(BackupJob("y", options=own)) is own
    assert BackupRunner([job]).options == BackupOptions()


def test_backup_folder_name():
    assert backup_folder_name(datetime(2026, 10, 6, 23, 59)) == f"{BACKUP_FOLDER_PREFIX} 06-10-2026"
    assert backup_folder_name() == daily_folder()


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


@pytest.mark.skipif(os.name != "nt", reason="буквы дисков есть только в Windows")
def test_folder_copy_name_for_windows_paths():
    assert folder_copy_name("C:" + chr(92)) == "Диск_C"
    assert folder_copy_name("C:" + chr(92) + "Users" + chr(92) + "x" + chr(92)) == "x"


def test_folder_copy_name():
    assert folder_copy_name("/home/user/docs") == "docs"
    assert folder_copy_name("/home/user/docs/") == "docs"
    assert folder_copy_name("/") == "Диск_root"


def test_describe_error_gives_short_reasons():
    busy = SimpleNamespace(winerror=32, errno=errno.EACCES, strerror="технический текст")
    assert describe_error(busy) == "файл занят другой программой"
    assert describe_error(PermissionError(errno.EACCES, "Permission denied")) == "нет доступа"
    assert describe_error(OSError(errno.ENOSPC, "No space left on device")) == "на диске недостаточно места"
    assert describe_error(OSError(99999, "редкая ошибка")) == "редкая ошибка"
    assert describe_error(ValueError("сбой")) == "сбой"


# --------------------------------------------------------------------------- только новые и измененные
CHANGED = BackupOptions(copy_only_changed=True)
ALL_COPIED = ["docs/a.txt", "docs/sub/b.txt", "single.txt"]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def shift_mtime(path, seconds):
    info = os.stat(path)
    os.utime(path, (info.st_atime, info.st_mtime + seconds))


def stamp_of(path):
    """Дата, которую получит прежняя копия: время ее изменения."""
    return datetime.fromtimestamp(os.stat(path).st_mtime).strftime(COPY_STAMP_FORMAT)


def test_only_changed_second_run_copies_nothing(tree):
    src, dst = tree
    _lines, first = run([job_for(src, dst)], CHANGED)
    assert first.status == STATUS_OK and first.message == "Успешно скопировано 3 файла"
    assert list_rel(dst) == ALL_COPIED
    _lines, second = run([job_for(src, dst)], CHANGED)
    assert second.status == STATUS_OK and second.copied_count == 0 and second.unchanged_count == 3
    assert second.message == "Новых и измененных файлов нет, без изменений: 3 файла"
    assert second.total_bytes == 0
    assert list_rel(dst) == ALL_COPIED  # ни docs_(1), ни single_(1): копия та же


def test_only_changed_keeps_previous_copy_of_changed_file(tree):
    src, dst = tree
    run([job_for(src, dst)], CHANGED)
    old_copy = os.path.join(dst, "docs", "a.txt")
    stamp = stamp_of(old_copy)
    source = os.path.join(src, "docs", "a.txt")
    write(source, "AAA")
    shift_mtime(source, 10)
    write(os.path.join(src, "docs", "c.txt"), "C")
    os.remove(os.path.join(src, "docs", "sub", "b.txt"))
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.status == STATUS_OK and result.copied_count == 2 and result.unchanged_count == 1
    assert result.message == "Успешно скопировано 2 файла, без изменений: 1 файл"
    assert read(old_copy) == "AAA"
    assert read(os.path.join(dst, "docs", f"a_{stamp}.txt")) == "A"  # прежняя копия с датой своего изменения
    # файл, удаленный из источника, в копии остается
    assert list_rel(dst) == sorted(ALL_COPIED + ["docs/c.txt", f"docs/a_{stamp}.txt"])


def test_only_changed_ignores_two_second_time_difference(tree):
    """FAT хранит время с шагом 2 секунды: такая разница — не изменение."""
    src, dst = tree
    run([job_for(src, dst)], CHANGED)
    copy = os.path.join(dst, "single.txt")
    shift_mtime(copy, 1.5)
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.copied_count == 0 and result.unchanged_count == 3
    shift_mtime(copy, 5)
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.copied_count == 1 and result.unchanged_count == 2
    assert len([name for name in os.listdir(dst) if name.startswith("single_")]) == 1


def test_only_changed_numbers_same_names_the_same_way_every_run(tmp_path):
    """Две папки «docs» и содержимое двух папок в одном месте: номера не меняются от запуска к запуску."""
    make_tree(tmp_path / "one", {"docs": {"x.txt": "1"}})
    make_tree(tmp_path / "two", {"docs": {"x.txt": "22"}})
    folders = [str(tmp_path / "one" / "docs"), str(tmp_path / "two" / "docs")]
    whole, merged = tmp_path / "whole", tmp_path / "merged"
    for _ in range(2):
        _lines, separate = run([BackupJob("a", folders, [], str(whole))], CHANGED)
        _lines, together = run([BackupJob("b", folders, [], str(merged))],
                               BackupOptions(copy_folder_contents=True, copy_only_changed=True))
    assert list_rel(whole) == ["docs/x.txt", "docs_(1)/x.txt"]
    assert list_rel(merged) == ["x.txt", "x_(1).txt"]
    assert read(merged / "x_(1).txt") == "22"
    assert separate.unchanged_count == 2 and together.unchanged_count == 2


def test_only_changed_needs_space_for_changes_only(tree, monkeypatch):
    src, dst = tree
    run([job_for(src, dst)], CHANGED)
    monkeypatch.setattr(copier_module, "free_space", lambda path: 0)
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.status == STATUS_OK and result.unchanged_count == 3  # копировать нечего — место не нужно
    write(os.path.join(src, "single.txt"), "SSSS")
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.total_bytes == 4  # только измененный файл
    assert any("Недостаточно свободного места" in error and "(нужно 0.0 MB)" in error for error in result.errors)


def test_only_changed_with_daily_folder_compares_within_the_day(tree):
    src, dst = tree
    for _ in range(2):
        _lines, result = run([job_for(src, dst)], BackupOptions(create_backup_folder=True, copy_only_changed=True))
    day = daily_folder()
    assert list_rel(dst) == [f"{day}/{name}" for name in ALL_COPIED]
    assert result.unchanged_count == 3


def test_only_changed_reports_folder_in_place_of_copy(tree):
    src, dst = tree
    os.makedirs(os.path.join(dst, "single.txt"))
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.status == STATUS_PARTIAL and result.copied_count == 2
    assert any("на месте копии уже есть папка" in error for error in result.errors)


def test_previous_copy_gets_number_when_its_dated_name_is_taken(tree):
    src, dst = tree
    run([job_for(src, dst)], CHANGED)
    stamp = stamp_of(os.path.join(dst, "single.txt"))
    write(os.path.join(dst, f"single_{stamp}.txt"), "занято")
    write(os.path.join(src, "single.txt"), "new")
    _lines, result = run([job_for(src, dst)], CHANGED)
    assert result.copied_count == 1 and read(os.path.join(dst, "single.txt")) == "new"
    assert read(os.path.join(dst, f"single_{stamp}_(1).txt")) == "S"
    assert read(os.path.join(dst, f"single_{stamp}.txt")) == "занято"


def test_changed_only_paths_number_and_shorten(tmp_path):
    root = str(tmp_path)
    paths = ChangedOnlyPaths(root, 0, claim_folder_files=False)
    assert paths.folder_base("docs") == os.path.join(root, "docs")
    assert paths.folder_base("docs") == os.path.join(root, "docs_(1)")
    # имена файлов из папок без слияния не запоминаются, явно выбранные файлы — запоминаются
    assert paths.target(root, "x.txt", True) == paths.target(root, "x.txt", True) == (os.path.join(root, "x.txt"), False)
    assert paths.target(root, "x.txt", False)[0] == os.path.join(root, "x.txt")
    assert paths.target(root, "x.txt", False)[0] == os.path.join(root, "x_(1).txt")
    # длинное имя укорачивается с запасом под дату прежней копии
    limited = ChangedOnlyPaths(root, len(root) + 1 + 60, claim_folder_files=False)
    target, shortened = limited.target(root, "д" * 80 + ".txt", True)
    assert shortened and target.endswith(".txt") and len(os.path.basename(target)) == 60 - 26
