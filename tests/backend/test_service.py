"""Сервис бэкенда целиком, без Qt: расписание, запуск, события, автозапуск."""
import os
import time
from datetime import datetime, timedelta

import pytest

from backup_app.backend import autostart
from backup_app.backend import copier as copier_module
from backup_app.backend.events import (BackupFinished, BackupProgress, BackupStarted, ConfigChanged,
                                       RunSkipped, ScheduleChanged)
from backup_app.backend.safety import system_paths
from backup_app.backend.service import (ALREADY_RUNNING, NO_DESTINATION, NO_SOURCES, NO_TABS_WITH_DATA,
                                        BackupService)
from backup_app.backend.settings_store import AppConfig, SettingsStore, TabConfig
from helpers import list_rel, make_tree

NOW = datetime(2026, 10, 6, 12, 0, 0)


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


def ready_config(paths, **overrides):
    src, dst = paths
    config = AppConfig(backup_time="10:00", create_backup_folder=False,
                       tabs=[TabConfig("Данные", [str(src / "docs")], [], str(dst))])
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def stored(service):
    return SettingsStore(service.settings_path).load()


def of_type(events, kind):
    return [event for event in events if isinstance(event, kind)]


def slow_copy(monkeypatch, delay=0.05):
    real = copier_module.shutil.copy2

    def copy2(source, target):
        time.sleep(delay)
        return real(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", copy2)


# ------------------------------------------------------------- копирование
def test_run_now_copies_in_background_and_reports(make_service, paths):
    _src, dst = paths
    service, events, _clock = make_service(ready_config(paths))
    assert service.run_now() == []
    assert service.wait_idle(10)
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]
    assert isinstance(events[0], BackupStarted) and events[0].scheduled is False
    assert events[0].tab_names == ("Данные",)
    assert of_type(events, BackupProgress)
    finished = of_type(events, BackupFinished)
    assert len(finished) == 1 and finished[0].result.status == "ok"
    assert isinstance(events[-1], BackupFinished)
    assert not service.is_running
    assert stored(service).last_backup_time == NOW


def test_run_now_returns_problems_without_running(make_service):
    service, events, _clock = make_service()
    assert service.run_now() == [NO_SOURCES, NO_DESTINATION]
    assert of_type(events, RunSkipped) == [RunSkipped(False, f"{NO_SOURCES}; {NO_DESTINATION}")]
    assert not of_type(events, BackupStarted)


def test_copy_all_tabs_needs_one_complete_tab(make_service, paths):
    config = ready_config(paths, copy_all_tabs=True)
    config.tabs = [TabConfig("Пустая"), config.tabs[0]]
    service, _events, _clock = make_service(config)
    assert service.problems() == []
    config.tabs = [TabConfig("Пустая")]
    service.update_config(config)
    assert service.problems() == [NO_TABS_WITH_DATA]


def test_second_run_while_running_is_skipped(make_service, paths, monkeypatch):
    src, dst = paths
    make_tree(src / "docs", {f"f{i}.txt": "x" for i in range(6)})
    slow_copy(monkeypatch)
    service, events, _clock = make_service(ready_config(paths))
    assert service.run_now() == []
    assert service.run_now(scheduled=True) == [ALREADY_RUNNING]
    assert RunSkipped(True, ALREADY_RUNNING) in events
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


def test_listener_errors_do_not_break_the_service(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))

    def broken(_event):
        raise RuntimeError("сбой подписчика")

    service.subscribe(broken)
    assert service.run_now() == []
    assert service.wait_idle(10)
    assert of_type(events, BackupFinished)


# --------------------------------------------------------------- расписание
def test_start_schedule_computes_next_run_and_persists(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    assert service.start_schedule() == []
    assert service.schedule_active
    assert service.next_run == datetime(2026, 10, 7, 10, 0)
    assert events[-1] == ScheduleChanged(True, datetime(2026, 10, 7, 10, 0))
    saved = stored(service)
    assert saved.timer_active is True and saved.timer_started_at == NOW


def test_start_schedule_with_problems_does_nothing(make_service):
    service, events, _clock = make_service()
    assert service.start_schedule() == [NO_SOURCES, NO_DESTINATION]
    assert not service.schedule_active and not events


def test_tick_runs_backup_when_due(make_service, paths):
    _src, dst = paths
    service, events, _clock = make_service(ready_config(paths))
    service.start_schedule()
    due = service.next_run
    assert service.tick(due - timedelta(seconds=1)) is False
    assert service.tick(due + timedelta(seconds=1)) is True
    assert service.next_run == due + timedelta(days=1)
    assert service.wait_idle(10)
    started = of_type(events, BackupStarted)
    assert started and started[0].scheduled is True
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]


def test_scheduled_problems_are_reported_not_raised(make_service, paths, log_records):
    service, events, _clock = make_service(ready_config(paths))
    service.start_schedule()
    empty = service.config
    empty.tabs = [TabConfig("Пустая")]
    service.update_config(empty)
    assert service.tick(service.next_run + timedelta(seconds=1)) is True
    assert of_type(events, RunSkipped)[-1].scheduled is True
    assert any("Плановое копирование не запущено" in line for line in log_records)
    assert service.schedule_active


def test_stop_schedule(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    service.start_schedule()
    service.stop_schedule()
    assert not service.schedule_active and service.next_run is None
    assert events[-1] == ScheduleChanged(False, None)
    assert stored(service).timer_active is False


def test_update_config_recomputes_next_run_and_keeps_service_fields(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))
    service.start_schedule()
    change = service.config
    change.backup_time = "23:59"
    change.timer_active = False      # служебное поле: окно его не меняет
    change.auto_start = True         # служебное поле: окно его не меняет
    service.update_config(change)
    assert service.schedule_active
    assert service.next_run == datetime(2026, 10, 6, 23, 59)
    assert events[-1] == ScheduleChanged(True, datetime(2026, 10, 6, 23, 59))
    saved = stored(service)
    assert saved.backup_time == "23:59" and saved.timer_active is True and saved.auto_start is False


def test_scheduler_thread_starts_backup_on_time(make_service, paths):
    _src, dst = paths
    service, events, clock = make_service(ready_config(paths), check_interval=0.05)
    service.start()
    service.start_schedule()
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
    assert stored(service) == AppConfig()


def test_resume_after_restart(make_service, paths):
    service, events, _clock = make_service(ready_config(paths, timer_active=True))
    service.start(run_scheduler=False)
    assert service.schedule_active
    assert ScheduleChanged(True, datetime(2026, 10, 7, 10, 0)) in events


def test_resume_with_all_tabs_when_active_tab_is_empty(make_service, paths):
    config = ready_config(paths, timer_active=True, copy_all_tabs=True)
    config.tabs = [config.tabs[0], TabConfig("Пустая")]
    config.active_tab = 1
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.schedule_active


def test_resume_impossible_without_sources(make_service, log_records):
    service, events, _clock = make_service(AppConfig(timer_active=True))
    service.start(run_scheduler=False)
    assert not service.schedule_active
    assert stored(service).timer_active is False
    assert any("Расписание не возобновлено" in line for line in log_records)
    assert ScheduleChanged(False, None) in events


def test_missed_run_executes_after_start(make_service, paths):
    _src, dst = paths
    config = ready_config(paths, timer_active=True, timer_started_at=NOW - timedelta(days=1))
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.tick() is True
    assert service.wait_idle(10)
    assert list_rel(dst) == ["docs/a.txt", "docs/sub/b.txt"]
    assert stored(service).last_backup_time == NOW


def test_no_missed_run_when_backup_is_recent(make_service, paths):
    config = ready_config(paths, timer_active=True, last_backup_time=NOW - timedelta(hours=1))
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.tick() is False


def test_missed_run_can_be_disabled(make_service, paths):
    config = ready_config(paths, timer_active=True, run_missed=False, timer_started_at=NOW - timedelta(days=1))
    service, _events, _clock = make_service(config)
    service.start(run_scheduler=False)
    assert service.tick() is False


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


def test_reset_restores_defaults_and_stops_schedule(make_service, paths):
    config = ready_config(paths, copy_all_tabs=True)
    config.tabs.append(TabConfig("Вторая"))
    service, events, _clock = make_service(config)
    service.start_schedule()
    assert service.reset() == AppConfig()
    assert not service.schedule_active
    assert stored(service) == AppConfig()
    assert of_type(events, ConfigChanged)[-1].config == AppConfig()
    assert events[-1] == ScheduleChanged(False, None)


# ---------------------------------------------------------- проверки путей
def test_path_checks_for_the_interface(make_service, tmp_path):
    service, _events, _clock = make_service()
    system = system_paths()[0]
    assert "Системная папка" in service.source_problem(system)
    assert "Системная папка" in service.destination_problem(system)
    assert service.source_problem(str(tmp_path)) is None
    assert service.destination_problem(str(tmp_path)) is None
    assert "недоступен" in service.path_problem(str(tmp_path / "нет"))
    assert service.path_problem(str(tmp_path)) is None
