"""Сервис бэкенда целиком, без Qt: расписание вкладок, запуск, события, автозапуск."""
import dataclasses
import os
import threading
import time
from datetime import datetime, timedelta

import pytest

from backup_app.backend import autostart
from backup_app.backend import copier as copier_module
from backup_app.backend import safety as safety_module
from backup_app.backend.copier import backup_folder_name
from backup_app.backend.events import (AppProblem, BackupFinished, BackupProgress, BackupStarted, ConfigChanged,
                                       HistoryAdded, RunSkipped, ScheduleChanged)
from backup_app.backend.safety import system_paths
from backup_app.backend.service import (ALREADY_RUNNING, NO_DESTINATION, NO_SOURCES, NO_TABS_WITH_DATA,
                                        BackupService)
from backup_app.backend.settings_store import AppConfig, SettingsStore, TabConfig
from helpers import list_rel, make_tree

NOW = datetime(2026, 10, 6, 12, 0, 0)       # вторник
NEXT = datetime(2026, 10, 7, 10, 0)         # следующее копирование вкладки «Данные» в 10:00


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


@pytest.fixture
def paths(tmp_path):
    src = tmp_path / "src"
    make_tree(src, {"docs": {"a.txt": "A", "sub": {"b.txt": "BB"}}})
    dst = tmp_path / "dst"
    dst.mkdir()
    return src, dst


@pytest.fixture
def photos(tmp_path):
    """Вторая вкладка «Фото» со своими источником и папкой назначения."""
    src = tmp_path / "src2"
    make_tree(src, {"photos": {"p.jpg": "P"}})
    dst = tmp_path / "dst2"
    dst.mkdir()
    return TabConfig(uid="photo", title="Фото", folders=[str(src / "photos")], destination=str(dst),
                     backup_time="10:00", create_backup_folder=False), dst


@pytest.fixture
def make_service(tmp_path):
    created = []

    def factory(config=None, now=NOW, **kwargs):
        store = SettingsStore(str(tmp_path / "settings.ini"))
        if config is not None:
            store.save(config)
        clock = Clock(now)
        kwargs.setdefault("missed_run_delay", 0)
        service = BackupService(store, now=clock, **kwargs)
        events = []
        service.subscribe(events.append)
        created.append(service)
        return service, events, clock

    yield factory
    for service in created:
        service.shutdown(timeout=5)


def ready_tab(paths, **overrides):
    src, dst = paths
    tab = TabConfig(uid="data", title="Данные", folders=[str(src / "docs")], destination=str(dst),
                    backup_time="10:00", create_backup_folder=False)
    return dataclasses.replace(tab, **overrides)


def ready_config(paths, *more_tabs, run_missed=True, **overrides):
    return AppConfig(run_missed=run_missed, tabs=[ready_tab(paths, **overrides), *more_tabs])


def empty_tab(uid="empty", title="Пустая", **overrides):
    return TabConfig(uid=uid, title=title, backup_time="10:00", **overrides)


def stored(service):
    return SettingsStore(service.settings_path).load()


def of_type(events, kind):
    return [event for event in events if isinstance(event, kind)]


def history_texts(service):
    return [entry.text for entry in service.history()]


def history_tabs(service):
    return [entry.tab_ids for entry in service.history()]


def slow_copy(monkeypatch, delay=0.05):
    real = copier_module.shutil.copy2

    def copy2(source, target):
        time.sleep(delay)
        return real(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", copy2)


def without_sources(service, uid):
    """Окно убирает источники вкладки uid."""
    change = service.config
    change.tab(uid).folders = []
    service.update_config(change)


# ------------------------------------------------------------- копирование
def test_run_now_copies_in_background_and_reports(make_service, paths):
    _src, dst = paths
    service, events, _clock = make_service(ready_config(paths))
    assert service.run_now() == []
    assert service.wait_idle(10)
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]
    assert events[0] == BackupStarted(False, ("Данные",), ("data",))
    assert of_type(events, BackupProgress)
    finished = of_type(events, BackupFinished)
    assert len(finished) == 1 and finished[0].result.status == "ok"
    assert finished[0].scheduled is False and finished[0].tab_ids == ("data",)
    assert isinstance(events[-1], BackupFinished)
    assert not service.is_running and service.running_tabs == ()
    assert stored(service).tab("data").last_backup_time == NOW


def test_run_now_returns_problems_without_running(make_service):
    service, events, _clock = make_service()
    uid = service.config.tabs[0].uid
    assert service.run_now([uid]) == [NO_SOURCES, NO_DESTINATION]
    assert service.run_now() == [NO_TABS_WITH_DATA]
    assert service.run_now(["нет такой вкладки"]) == [NO_TABS_WITH_DATA]
    assert of_type(events, RunSkipped)[:2] == [RunSkipped(False, f"{NO_SOURCES}; {NO_DESTINATION}"),
                                               RunSkipped(False, NO_TABS_WITH_DATA)]
    assert not of_type(events, BackupStarted)
    assert service.history() == []


def test_run_all_tabs_skips_tabs_without_data(make_service, paths, photos):
    photo_tab, photo_dst = photos
    service, events, _clock = make_service(ready_config(paths, empty_tab(), photo_tab))
    assert service.problems() == [] and service.problems("empty") == [NO_SOURCES, NO_DESTINATION]
    assert service.run_now() == []
    assert service.wait_idle(10)
    assert of_type(events, BackupStarted) == [BackupStarted(False, ("Данные", "Фото"), ("data", "photo"))]
    assert list_rel(photo_dst) == ["photos/p.jpg"]
    assert history_texts(service) == ["Ручное копирование: Данные, Фото", "✓ Успешно скопировано 3 файла из 2 вкладок"]
    assert history_tabs(service) == [("data", "photo"), ("data", "photo")]
    only_empty = service.config
    only_empty.tabs = [only_empty.tab("empty")]
    service.update_config(only_empty)
    assert service.problems() == [NO_TABS_WITH_DATA]


def test_run_one_tab_copies_only_it(make_service, paths, photos):
    _src, dst = paths
    photo_tab, photo_dst = photos
    service, events, _clock = make_service(ready_config(paths, photo_tab))
    assert service.run_now(["photo"]) == []
    assert service.wait_idle(10)
    assert list_rel(photo_dst) == ["photos/p.jpg"] and list_rel(dst) == []
    assert of_type(events, BackupStarted) == [BackupStarted(False, ("Фото",), ("photo",))]
    saved = stored(service)
    assert saved.tab("photo").last_backup_time == NOW and saved.tab("data").last_backup_time is None


def test_failed_run_does_not_mark_last_backup(make_service, paths, tmp_path):
    service, _events, _clock = make_service(ready_config(paths, folders=[str(tmp_path / "нет")]))
    service.run_now()
    assert service.wait_idle(10)
    assert service.history()[-1].text.startswith("✗ Нет файлов для копирования")
    assert stored(service).tab("data").last_backup_time is None


def test_jobs_use_options_of_their_tabs(make_service, paths, photos):
    _src, dst = paths
    photo_tab, photo_dst = photos
    photo_tab.create_backup_folder = True
    config = ready_config(paths, photo_tab, copy_folder_contents=True)
    service, _events, _clock = make_service(config)
    assert service.run_now() == []
    assert service.wait_idle(10)
    assert list_rel(dst) == ["a.txt", "sub/b.txt"]
    assert list_rel(photo_dst) == [f"{backup_folder_name()}/photos/p.jpg"]


def test_second_run_while_running_is_skipped(make_service, paths, monkeypatch):
    src, dst = paths
    make_tree(src / "docs", {f"f{i}.txt": "x" for i in range(6)})
    slow_copy(monkeypatch)
    service, events, _clock = make_service(ready_config(paths))
    assert service.run_now() == []
    assert service.running_tabs == ("data",)
    assert service.run_now(["data"]) == [ALREADY_RUNNING]
    assert service.run_now(["data"], scheduled=True) == [ALREADY_RUNNING]
    assert RunSkipped(False, ALREADY_RUNNING) in events and RunSkipped(True, ALREADY_RUNNING) in events
    assert service.wait_idle(10)
    assert len(of_type(events, BackupFinished)) == 1
    assert len(list_rel(dst)) == 8


def test_cancel_and_shutdown_stop_running_backup(make_service, paths, monkeypatch):
    src, _dst = paths
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(30)})
    slow_copy(monkeypatch)
    service, events, _clock = make_service(ready_config(paths))
    service.run_now()
    time.sleep(0.2)
    service.shutdown(timeout=5)
    assert not service.is_running
    assert of_type(events, BackupFinished)[0].result.status == "cancelled"


def test_cancel_stops_running_backup(make_service, paths, monkeypatch):
    src, _dst = paths
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(30)})
    slow_copy(monkeypatch)
    service, events, _clock = make_service(ready_config(paths))
    service.run_now()
    time.sleep(0.2)
    service.cancel()
    assert service.wait_idle(10)
    finished = of_type(events, BackupFinished)
    assert finished[0].result.status == "cancelled" and finished[0].tab_ids == ("data",)
    assert history_tabs(service)[-1] == ("data",)


def test_listener_errors_do_not_break_the_service(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))

    def broken(_event):
        raise RuntimeError("сбой подписчика")

    service.subscribe(broken)
    assert service.run_now() == []
    assert service.wait_idle(10)
    assert of_type(events, BackupFinished)


# --------------------------------------------------------------- расписание
def test_set_tab_schedule_computes_next_run_and_persists(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    assert not service.schedule_active and service.next_run is None
    assert service.set_tab_schedule("data", True) == []
    assert service.schedule_active
    assert service.next_run == NEXT and service.next_runs() == {"data": NEXT}
    assert events[-1] == ScheduleChanged((("data", NEXT),))
    assert events[-1].active and events[-1].next_run == NEXT and events[-1].nearest == ("data", NEXT)
    saved = stored(service).tab("data")
    assert saved.schedule_on is True and saved.timer_started_at == NOW
    assert history_texts(service) == ["Расписание запущено: Данные, следующее копирование: 07.10.2026 10:00"]
    assert history_tabs(service) == [("data",)]
    assert service.set_tab_schedule("data", True) == []  # уже включено: ничего не меняется
    assert len(service.history()) == 1


def test_set_tab_schedule_with_problems_does_nothing(make_service):
    service, events, _clock = make_service()
    uid = service.config.tabs[0].uid
    assert service.set_tab_schedule(uid, True) == [NO_SOURCES, NO_DESTINATION]
    assert not service.schedule_active and not events and service.history() == []
    assert stored(service).tabs[0].schedule_on is False


def test_set_tab_schedule_off(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    service.set_tab_schedule("data", True)
    assert service.set_tab_schedule("data", False) == []
    assert not service.schedule_active and service.next_run is None and service.next_runs() == {}
    assert events[-1] == ScheduleChanged(())
    assert not events[-1].active and events[-1].next_run is None and events[-1].nearest is None
    assert stored(service).tab("data").schedule_on is False
    service.set_tab_schedule("data", False)
    assert history_texts(service)[1:] == ["Расписание остановлено: Данные"]
    assert history_tabs(service)[1:] == [("data",)]


def test_each_tab_has_its_own_schedule(make_service, paths, photos):
    photo_tab, _dst = photos
    photo_tab.period_type, photo_tab.weekday, photo_tab.backup_time = "Еженедельно", 6, "22:00"
    service, events, _clock = make_service(ready_config(paths, photo_tab))
    service.set_tab_schedule("photo", True)
    service.set_tab_schedule("data", True)
    sunday = datetime(2026, 10, 11, 22, 0)
    assert service.next_runs() == {"data": NEXT, "photo": sunday}
    assert service.next_run == NEXT
    assert events[-1] == ScheduleChanged((("data", NEXT), ("photo", sunday)))
    assert events[-1].nearest == ("data", NEXT)
    service.set_tab_schedule("data", False)
    assert service.next_run == sunday and service.schedule_active


def test_tick_runs_backup_when_due(make_service, paths):
    _src, dst = paths
    service, events, _clock = make_service(ready_config(paths))
    service.set_tab_schedule("data", True)
    assert service.tick(NEXT - timedelta(seconds=1)) is False
    assert service.tick(NEXT + timedelta(seconds=1)) is True
    assert service.next_run == NEXT + timedelta(days=1)
    assert ScheduleChanged((("data", NEXT + timedelta(days=1)),)) in events
    assert service.wait_idle(10)
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Данные",), ("data",))]
    assert of_type(events, BackupFinished)[0].scheduled is True
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]


def test_tick_with_two_due_tabs_starts_one_run_with_their_options(make_service, paths, photos):
    _src, dst = paths
    photo_tab, photo_dst = photos
    photo_tab.create_backup_folder = True
    service, events, _clock = make_service(ready_config(paths, photo_tab, copy_folder_contents=True))
    service.set_tab_schedule("data", True)
    service.set_tab_schedule("photo", True)
    assert service.tick(NEXT + timedelta(seconds=30)) is True
    assert service.wait_idle(10)
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Данные", "Фото"), ("data", "photo"))]
    assert len(of_type(events, BackupFinished)) == 1
    assert service.next_runs() == {"data": NEXT + timedelta(days=1), "photo": NEXT + timedelta(days=1)}
    assert list_rel(dst) == ["a.txt", "sub/b.txt"]
    assert list_rel(photo_dst) == [f"{backup_folder_name()}/photos/p.jpg"]
    assert history_texts(service)[2:] == ["Плановое копирование: Данные, Фото",
                                          "✓ Успешно скопировано 3 файла из 2 вкладок"]
    assert history_tabs(service)[2:] == [("data", "photo"), ("data", "photo")]


def test_due_tab_with_problems_does_not_stop_other_tabs(make_service, paths, photos, log_records):
    photo_tab, _photo_dst = photos
    service, events, _clock = make_service(ready_config(paths, photo_tab))
    service.set_tab_schedule("data", True)
    service.set_tab_schedule("photo", True)
    without_sources(service, "data")
    assert service.tick(NEXT + timedelta(seconds=1)) is True
    assert service.wait_idle(10)
    assert of_type(events, RunSkipped) == [RunSkipped(True, NO_SOURCES)]
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Фото",), ("photo",))]
    assert history_texts(service)[2:] == [
        f"✗ Плановое копирование не запущено (Данные): {NO_SOURCES}",
        "Плановое копирование: Фото",
        "✓ Успешно скопировано 1 файл",
    ]
    assert history_tabs(service)[2:] == [("data",), ("photo",), ("photo",)]
    assert any("Плановое копирование не запущено (Данные)" in line for line in log_records)
    assert service.next_runs() == {"data": NEXT + timedelta(days=1), "photo": NEXT + timedelta(days=1)}


def test_scheduled_problems_are_reported_not_raised(make_service, paths, log_records):
    service, events, _clock = make_service(ready_config(paths))
    service.set_tab_schedule("data", True)
    empty = service.config
    empty.tabs = [dataclasses.replace(empty.tabs[0], folders=[], destination="")]
    service.update_config(empty)
    assert service.tick(service.next_run + timedelta(seconds=1)) is True
    assert of_type(events, RunSkipped)[-1] == RunSkipped(True, f"{NO_SOURCES}; {NO_DESTINATION}")
    assert any("Плановое копирование не запущено" in line for line in log_records)
    assert service.schedule_active and not of_type(events, BackupStarted)


def test_due_tabs_while_copying_are_recorded_per_tab(make_service, paths, photos, monkeypatch):
    src, _dst = paths
    make_tree(src / "docs", {f"f{number:02d}.txt": "x" for number in range(10)})
    slow_copy(monkeypatch)
    photo_tab, _photo_dst = photos
    service, events, _clock = make_service(ready_config(paths, photo_tab))
    service.set_tab_schedule("data", True)
    service.set_tab_schedule("photo", True)
    service.run_now(["data"])
    assert service.tick(NEXT + timedelta(seconds=1)) is True
    assert RunSkipped(True, ALREADY_RUNNING) in events
    assert service.wait_idle(10)
    assert history_texts(service)[2:5] == [
        "Ручное копирование: Данные",
        "⚠ Плановое копирование не запущено: в это время шло другое копирование (Данные)",
        "⚠ Плановое копирование не запущено: в это время шло другое копирование (Фото)",
    ]
    assert history_tabs(service)[3:5] == [("data",), ("photo",)]
    assert len(of_type(events, BackupStarted)) == 1


def test_update_config_recomputes_next_run_and_keeps_service_fields(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    service.set_tab_schedule("data", True)
    change = service.config
    tab = change.tab("data")
    tab.backup_time = "23:59"
    tab.schedule_on = False                            # служебное поле: окно его не меняет
    tab.timer_started_at = None                        # служебное поле: окно его не меняет
    tab.last_backup_time = datetime(2000, 1, 1)        # служебное поле: окно его не меняет
    change.auto_start = True                           # служебное поле: окно его не меняет
    service.update_config(change)
    assert service.schedule_active
    assert service.next_run == datetime(2026, 10, 6, 23, 59)
    assert events[-1] == ScheduleChanged((("data", datetime(2026, 10, 6, 23, 59)),))
    saved = stored(service)
    assert saved.tab("data").backup_time == "23:59" and saved.tab("data").schedule_on is True
    assert saved.tab("data").timer_started_at == NOW and saved.tab("data").last_backup_time is None
    assert saved.auto_start is False


def test_update_config_without_schedule_changes_keeps_next_run(make_service, paths):
    service, events, clock = make_service(ready_config(paths))
    service.set_tab_schedule("data", True)
    count = len(of_type(events, ScheduleChanged))
    clock.moment = NEXT + timedelta(seconds=5)   # время подошло, но планировщик еще не проверял
    change = service.config
    change.tab("data").title = "Новое имя"
    change.tab("data").keep_history = False
    service.update_config(change)
    assert len(of_type(events, ScheduleChanged)) == count
    assert service.next_run == NEXT
    assert stored(service).tab("data").title == "Новое имя"


def test_update_config_new_tab_starts_without_schedule(make_service, paths, photos):
    photo_tab, _dst = photos
    service, _events, _clock = make_service(ready_config(paths))
    change = service.config
    change.tabs.append(dataclasses.replace(photo_tab, schedule_on=True, last_backup_time=NOW))
    service.update_config(change)
    saved = stored(service).tab("photo")
    assert saved.schedule_on is False and saved.last_backup_time is None
    assert service.next_runs() == {}


def test_removing_scheduled_tab_stops_its_schedule(make_service, paths, photos):
    photo_tab, _dst = photos
    service, events, _clock = make_service(ready_config(paths, photo_tab))
    service.set_tab_schedule("photo", True)
    change = service.config
    change.tabs = [change.tab("data")]
    service.update_config(change)
    assert not service.schedule_active
    assert events[-1] == ScheduleChanged(())
    assert history_texts(service)[-1] == "Расписание остановлено: Фото"
    assert history_tabs(service)[-1] == ("photo",)
    assert service.tick(NEXT + timedelta(seconds=1)) is False


def test_scheduler_thread_starts_backup_on_time(make_service, paths):
    _src, dst = paths
    service, events, clock = make_service(ready_config(paths), check_interval=0.05)
    service.start()
    service.set_tab_schedule("data", True)
    clock.moment = service.next_run + timedelta(seconds=1)
    deadline = time.monotonic() + 10
    while not of_type(events, BackupFinished) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert of_type(events, BackupFinished)
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]


# ------------------------------------------------ возобновление после запуска
def test_first_start_creates_settings_file(make_service):
    service, _events, _clock = make_service()
    assert not os.path.exists(service.settings_path)
    service.start(run_scheduler=False)
    assert os.path.exists(service.settings_path)
    assert stored(service) == service.config


def test_resume_after_restart(make_service, paths):
    service, events, _clock = make_service(ready_config(paths, schedule_on=True))
    assert not service.schedule_active
    service.start(run_scheduler=False)
    assert service.schedule_active
    assert ScheduleChanged((("data", NEXT),)) in events
    assert service.history() == []


def test_resume_of_legacy_schedule_for_all_tabs(make_service, paths, photos, tmp_path):
    """Файл версии 9 с «копировать все вкладки»: расписание возобновляется у всех вкладок с данными."""
    photo_tab, _dst = photos
    src, dst = paths
    (tmp_path / "settings.ini").write_text(
        "[General]\nbackup_time=10:00\ntimer_active=true\ncopy_all_tabs=true\nactive_tab=1\ntab_count=3\n"
        f"[Tab_0]\ntab_title=Данные\nsource_folders={src / 'docs'}\ndestination_folder={dst}\n"
        "[Tab_1]\ntab_title=Пустая\n"
        f"[Tab_2]\ntab_title=Фото\nsource_folders={photo_tab.folders[0]}\n"
        f"destination_folder={photo_tab.destination}\n", encoding="utf-8")
    service, _events, _clock = make_service()
    service.start(run_scheduler=False)
    config = service.config
    assert [tab.schedule_on for tab in config.tabs] == [True, False, True]
    assert sorted(service.next_runs().values()) == [NEXT, NEXT]


def test_resume_with_problems_turns_off_only_that_tab(make_service, paths, photos, log_records):
    photo_tab, _dst = photos
    broken = dataclasses.replace(photo_tab, destination="", schedule_on=True)
    service, events, _clock = make_service(ready_config(paths, broken, schedule_on=True))
    service.start(run_scheduler=False)
    assert service.next_runs() == {"data": NEXT}
    assert ScheduleChanged((("data", NEXT),)) in events
    saved = stored(service)
    assert saved.tab("data").schedule_on is True and saved.tab("photo").schedule_on is False
    assert history_texts(service) == [f"✗ Расписание не возобновлено (Фото): {NO_DESTINATION}"]
    assert history_tabs(service) == [("photo",)]
    assert any("Расписание не возобновлено (Фото)" in line for line in log_records)


def test_resume_impossible_without_sources(make_service, log_records):
    service, events, _clock = make_service(AppConfig(tabs=[empty_tab(schedule_on=True)]))
    service.start(run_scheduler=False)
    assert not service.schedule_active
    assert stored(service).tabs[0].schedule_on is False
    assert any("Расписание не возобновлено" in line for line in log_records)
    assert ScheduleChanged(()) in events
    assert history_texts(service) == [f"✗ Расписание не возобновлено (Пустая): {NO_SOURCES}; {NO_DESTINATION}"]


def test_missed_run_executes_after_start(make_service, paths):
    _src, dst = paths
    config = ready_config(paths, schedule_on=True, timer_started_at=NOW - timedelta(days=1))
    service, events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.tick() is True
    assert service.wait_idle(10)
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Данные",), ("data",))]
    assert stored(service).tab("data").last_backup_time == NOW
    assert service.tick() is False


def test_missed_run_is_checked_per_tab(make_service, paths, photos):
    photo_tab, _dst = photos
    recent = dataclasses.replace(photo_tab, schedule_on=True, last_backup_time=NOW - timedelta(hours=1))
    config = ready_config(paths, recent, schedule_on=True, timer_started_at=NOW - timedelta(days=1))
    service, events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert history_texts(service) == ["⚠ Пропущено плановое копирование 06.10.2026 10:00, выполняется сейчас (Данные)"]
    assert history_tabs(service) == [("data",)]
    assert service.tick() is True
    assert service.wait_idle(10)
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Данные",), ("data",))]


def test_missed_tabs_run_together(make_service, paths, photos):
    photo_tab, _dst = photos
    day_ago = NOW - timedelta(days=1)
    missed = dataclasses.replace(photo_tab, schedule_on=True, timer_started_at=day_ago)
    service, events, _clock = make_service(ready_config(paths, missed, schedule_on=True, timer_started_at=day_ago))
    service.start(run_scheduler=False)
    assert len(service.history()) == 2
    assert service.tick() is True
    assert service.wait_idle(10)
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Данные", "Фото"), ("data", "photo"))]


def test_missed_run_is_forgotten_when_schedule_is_turned_off(make_service, paths):
    config = ready_config(paths, schedule_on=True, timer_started_at=NOW - timedelta(days=1))
    service, _events, _clock = make_service(config, missed_run_delay=60)
    service.start(run_scheduler=False)
    service.set_tab_schedule("data", False)
    assert service.tick(NOW + timedelta(minutes=5)) is False


def test_no_missed_run_when_backup_is_recent(make_service, paths):
    config = ready_config(paths, schedule_on=True, last_backup_time=NOW - timedelta(hours=1))
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.tick() is False


def test_missed_run_can_be_disabled(make_service, paths):
    config = ready_config(paths, run_missed=False, schedule_on=True, timer_started_at=NOW - timedelta(days=1))
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.tick() is False
    assert service.history() == []


# ---------------------------------------------------- автозапуск и сброс
def test_autostart_state_is_synced_on_start(make_service, monkeypatch):
    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    service, events, _clock = make_service()
    service.start(run_scheduler=False)
    assert of_type(events, ConfigChanged)[0].config.auto_start is True
    assert stored(service).auto_start is True


def test_set_autostart_failure_raises_and_keeps_setting(make_service, monkeypatch):
    def broken():
        raise OSError("реестр недоступен")

    monkeypatch.setattr(autostart, "enable", broken)
    service, _events, _clock = make_service()
    with pytest.raises(OSError):
        service.set_autostart(True)
    assert stored(service).auto_start is False


def defaults_without_uid(config):
    return dataclasses.replace(config, tabs=[dataclasses.replace(tab, uid="") for tab in config.tabs])


def test_reset_restores_defaults_and_stops_schedule(make_service, paths, photos):
    photo_tab, _dst = photos
    config = ready_config(paths, photo_tab, run_missed=False, keep_history=False, copy_folder_contents=True)
    config.minimize_to_tray = False
    service, events, _clock = make_service(config)
    service.set_tab_schedule("data", True)
    service.set_tab_schedule("photo", True)
    reset = service.reset()
    assert defaults_without_uid(reset) == defaults_without_uid(AppConfig())
    tab = reset.tabs[0]
    assert tab.keep_history and tab.create_backup_folder and not tab.copy_folder_contents
    assert not service.schedule_active and service.next_runs() == {}
    assert stored(service) == reset
    assert of_type(events, ConfigChanged)[-1].config == reset
    assert events[-1] == ScheduleChanged(())
    assert history_texts(service)[-1] == "Расписание остановлено: настройки сброшены"
    assert service.tick(NEXT + timedelta(seconds=1)) is False


def test_reset_without_schedule_adds_no_history(make_service, paths):
    service, _events, _clock = make_service(ready_config(paths))
    service.reset()
    assert service.history() == []


# ---------------------------------------------------------- проверки путей
def test_path_checks_for_the_interface(make_service, tmp_path):
    service, _events, _clock = make_service()
    system = system_paths()[0]
    assert "Системная папка" in service.source_problem(system)
    assert "Системная папка" in service.destination_problem(system)
    assert service.source_problem(str(tmp_path)) is None
    assert service.destination_problem(str(tmp_path)) is None
    assert service.path_problem(str(tmp_path / "нет")) == safety_module.PATH_UNAVAILABLE
    assert service.path_problem(system) == safety_module.PATH_SYSTEM
    assert service.path_problem(str(tmp_path)) is None


# --------------------------------------------------------- история копирования
def test_history_records_manual_backup_and_result(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    assert service.run_now(["data"]) == []
    assert service.wait_idle(10)
    assert history_texts(service) == ["Ручное копирование: Данные", "✓ Успешно скопировано 2 файла"]
    assert history_tabs(service) == [("data",), ("data",)]
    assert [event.entry for event in of_type(events, HistoryAdded)] == service.history()
    assert all(entry.time == NOW for entry in service.history())


def test_history_survives_restart(make_service, paths):
    service, _events, _clock = make_service(ready_config(paths))
    service.run_now()
    assert service.wait_idle(10)
    service.shutdown()
    again, _events, _clock = make_service()
    assert history_texts(again) == ["Ручное копирование: Данные", "✓ Успешно скопировано 2 файла"]
    assert history_tabs(again) == [("data",), ("data",)]
    assert os.path.dirname(again.history_path) == os.path.dirname(again.settings_path)


def test_history_lists_errors_and_files_over_the_limit(make_service, paths, monkeypatch):
    src, _dst = paths
    (src / "docs" / "big.bin").write_bytes(b"x" * 4096)
    monkeypatch.setattr(safety_module, "GB", 1024)  # лимит 2 ГБ превращается в 2 КБ
    real = copier_module.shutil.copy2

    def failing(source, target):
        if source.endswith("a.txt"):
            raise PermissionError(13, "Отказано в доступе")
        return real(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", failing)
    service, _events, _clock = make_service(ready_config(paths))
    service.run_now()
    assert service.wait_idle(10)
    result = service.history()[-1]
    assert result.text == "⚠ Скопировано 1 файл, ошибок: 1; пропущено по правилам безопасности: 1"
    assert len(result.details) == 2
    assert result.details[0].startswith("Не скопирован ") and result.details[0].endswith("a.txt: нет доступа")
    assert "больше" in result.details[1] and result.details[1].endswith("big.bin")
    assert stored(service).tab("data").last_backup_time == NOW  # частичный успех тоже отмечается


def test_history_records_schedule_and_skipped_runs(make_service, paths):
    service, _events, _clock = make_service(ready_config(paths))
    assert service.set_tab_schedule("data", True) == []
    empty = service.config
    empty.tabs = [dataclasses.replace(empty.tabs[0], title="Пустая", folders=[], destination="")]
    service.update_config(empty)
    service.tick(service.next_run + timedelta(seconds=1))
    service.set_tab_schedule("data", False)
    service.set_tab_schedule("data", False)
    assert history_texts(service) == [
        "Расписание запущено: Данные, следующее копирование: 07.10.2026 10:00",
        f"✗ Плановое копирование не запущено (Пустая): {NO_SOURCES}; {NO_DESTINATION}",
        "Расписание остановлено: Пустая",
    ]
    assert history_tabs(service) == [("data",)] * 3


def test_history_records_scheduled_run_while_copying(make_service, paths, monkeypatch):
    src, _dst = paths
    make_tree(src / "docs", {f"f{number:02d}.txt": "x" for number in range(10)})
    slow_copy(monkeypatch)
    service, _events, _clock = make_service(ready_config(paths))
    service.run_now()
    service.run_now(["data"], scheduled=True)
    assert service.wait_idle(10)
    assert history_texts(service)[1] == ("⚠ Плановое копирование не запущено: в это время шло другое копирование "
                                         "(Данные)")


def test_history_records_missed_run(make_service, paths):
    config = ready_config(paths, schedule_on=True, timer_started_at=NOW - timedelta(days=1))
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert history_texts(service) == ["⚠ Пропущено плановое копирование 06.10.2026 10:00, выполняется сейчас (Данные)"]
    assert service.tick() is True
    assert service.wait_idle(10)
    assert history_texts(service)[1:] == ["Плановое копирование: Данные", "✓ Успешно скопировано 2 файла"]


def test_history_records_backup_interrupted_by_exit(make_service, paths, monkeypatch):
    src, dst = paths
    make_tree(src / "docs", {f"f{number:02d}.txt": "x" for number in range(30)})
    slow_copy(monkeypatch)
    service, _events, _clock = make_service(ready_config(paths))
    service.run_now()
    deadline = time.monotonic() + 5
    while not list_rel(dst) and time.monotonic() < deadline:
        time.sleep(0.01)
    service.shutdown(timeout=5)
    texts = history_texts(service)
    assert texts[0] == "Ручное копирование: Данные" and len(texts) == 2
    assert texts[1].startswith("✗ Копирование прервано при выходе из приложения, скопировано ")
    assert history_tabs(service) == [("data",), ("data",)]


def test_settings_write_failure_is_shown_once(make_service, paths, monkeypatch):
    service, events, _clock = make_service(ready_config(paths))
    failing = [True]
    real_save = service._store.save

    def save(config):
        if failing[0]:
            raise PermissionError(13, "Отказано в доступе")
        real_save(config)

    monkeypatch.setattr(service._store, "save", save)
    for _ in range(3):
        service.update_config(service.config)
    problems = of_type(events, AppProblem)
    assert len(problems) == 1 and problems[0].title == "Не удалось сохранить настройки"
    failing[0] = False
    service.update_config(service.config)
    failing[0] = True
    service.update_config(service.config)
    assert len(of_type(events, AppProblem)) == 2


def lock_is_free(service):
    """True, если другой поток может взять блокировку сервиса: подписчик вызван вне ее."""
    thread = threading.Thread(target=lambda: service.is_running)
    thread.start()
    thread.join(2)
    return not thread.is_alive()


def test_settings_write_failure_is_reported_outside_lock(make_service, paths, monkeypatch):
    service, _events, _clock = make_service(ready_config(paths))
    free = []

    def listener(event):
        if isinstance(event, AppProblem):
            free.append(lock_is_free(service))

    service.subscribe(listener)
    calls = [
        lambda: service.update_config(service.config),
        lambda: service.set_autostart(True),
        lambda: service.set_tab_schedule("data", True),
        lambda: service.set_tab_schedule("data", False),
        lambda: service.shutdown(timeout=5),
    ]
    for call in calls:
        monkeypatch.setattr(service, "_settings_write_failed", False)   # каждый сбой снова показывается
        monkeypatch.setattr(service._store, "save", _failing_save)
        call()
    assert free == [True] * len(calls)


def _failing_save(config):
    raise PermissionError(13, "Отказано в доступе")


def test_schedule_event_is_not_stale_when_scheduler_ticks_meanwhile(make_service, paths, photos, monkeypatch):
    """Планировщик сдвигает расписание вкладки, пока другой поток включает расписание второй."""
    photo, _dst = photos
    photo = dataclasses.replace(photo, backup_time="13:00")
    service, events, clock = make_service(ready_config(paths, photo))
    service.start(run_scheduler=False)
    service.set_tab_schedule("data", True)
    real_record = service._record

    def record(text, *args, **kwargs):
        if text.startswith("Расписание запущено: Фото"):
            clock.moment = NEXT
            ticking = threading.Thread(target=service.tick, args=(NEXT,))
            ticking.start()
            ticking.join(5)
        real_record(text, *args, **kwargs)

    monkeypatch.setattr(service, "_record", record)
    service.set_tab_schedule("photo", True)
    service.wait_idle(5)
    last = of_type(events, ScheduleChanged)[-1]
    assert dict(last.next_runs) == service.next_runs()
    assert last.next_runs == (("data", NEXT + timedelta(days=1)), ("photo", datetime(2026, 10, 7, 13, 0)))


def test_schedule_change_during_delivery_is_sent_again(make_service, paths, photos):
    """Пока подписчик получает снимок, расписание меняется: следом приходит новый снимок."""
    photo, _dst = photos
    service, events, _clock = make_service(ready_config(paths, photo))
    inside, release = threading.Event(), threading.Event()

    def slow_listener(event):
        if isinstance(event, ScheduleChanged) and not inside.is_set():
            inside.set()
            release.wait(5)

    service.subscribe(slow_listener)
    first = threading.Thread(target=service.set_tab_schedule, args=("data", True))
    first.start()
    assert inside.wait(5)
    assert service.set_tab_schedule("photo", True) == []   # снимок отправит поток, который уже рассылает
    release.set()
    first.join(5)
    snapshots = of_type(events, ScheduleChanged)
    assert snapshots[-1].next_runs == (("data", NEXT), ("photo", NEXT))
    assert len(snapshots) == 2
