"""Окно поверх настоящего бэкенда: команды уходят в сервис, события приходят обратно."""
import time
from datetime import timedelta

import pytest
from PyQt5.QtCore import QTime

from backup_app.backend import AppConfig, BackupService, SettingsStore, setup_file_logging
from backup_app.backend import autostart
from backup_app.backend import copier as copier_module
from backup_app.backend.safety import system_paths
from backup_app.frontend import main_window as mw
from backup_app.frontend.bridge import ServiceBridge
from backup_app.frontend.tray import TrayIcon
from helpers import list_rel, make_tree, wait_for

SRC = {"docs": {"a.txt": "A", "sub": {"b.txt": "BB"}}, "single.txt": "S"}


class FakeMessageBox:
    Warning = 0
    YesRole = 0
    NoRole = 1
    calls = []

    @staticmethod
    def warning(*args, **_kwargs):
        FakeMessageBox.calls.append(("warning",) + tuple(args[1:3]))

    @staticmethod
    def information(*args, **_kwargs):
        FakeMessageBox.calls.append(("information",) + tuple(args[1:3]))

    @staticmethod
    def critical(*args, **_kwargs):
        FakeMessageBox.calls.append(("critical",) + tuple(args[1:3]))


@pytest.fixture
def env(qapp, config_dir, monkeypatch):
    """Окно с настоящим сервисом. Диалоги и уведомления записываются в списки."""
    FakeMessageBox.calls = []
    notifications = []

    def fake_notify(_tray, title, message, kind="info", msecs=6000):
        notifications.append((kind, title, message))

    monkeypatch.setattr(TrayIcon, "available", staticmethod(lambda: True))
    monkeypatch.setattr(TrayIcon, "notify", fake_notify)
    monkeypatch.setattr(mw, "QMessageBox", FakeMessageBox)
    created = []

    class Env:
        dialogs = FakeMessageBox.calls
        app = qapp
        dir = config_dir

        def ini(self):
            return config_dir / "settings.ini"

        def window(self, ini_text=None):
            if ini_text is not None:
                self.ini().write_text(ini_text, encoding="utf-8")
            log_path = setup_file_logging(str(config_dir / "logs"))
            service = BackupService(SettingsStore(str(self.ini())), missed_run_delay=0, log_path=log_path)
            bridge = ServiceBridge(service)
            window = mw.MainWindow(service, bridge)
            created.append((window, bridge, service))
            service.start(run_scheduler=False)
            return window

        def stored(self):
            return SettingsStore(str(self.ini())).load()

        def log_file(self):
            path = config_dir / "logs" / "backup-app.log"
            return path.read_text(encoding="utf-8") if path.exists() else ""

    Env.notifications = notifications
    yield Env()
    for window, bridge, service in created:
        service.cancel()
        service.wait_idle(5)
        qapp.processEvents()
        bridge.close()
        window.deleteLater()
    qapp.processEvents()


def fill_tab(window, folders=(), files=(), destination=""):
    page = window.current_page()
    for folder in folders:
        page.add_folder_path(str(folder))
    page.add_file_paths([str(path) for path in files])
    if destination:
        page.set_destination(str(destination))
    return page


def wait_backup(env, window):
    return wait_for(env.app, lambda: not window._running and not window.service.is_running)


def log_text(window):
    return window.log_text.toPlainText()


def ini_path(path):
    """В INI обратная косая черта экранируется, поэтому пути пишем с прямой."""
    return str(path).replace("\\", "/")


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    make_tree(src, SRC)
    dst = tmp_path / "dst"
    dst.mkdir()
    return src, dst


def slow_copy(monkeypatch, delay=0.05):
    real = copier_module.shutil.copy2

    def copy2(source, target):
        time.sleep(delay)
        return real(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", copy2)


# ------------------------------------------------------------------ старт
def test_fresh_start_creates_log_and_tray(env):
    window = env.window()
    assert window.tabs_widget.count() == 1
    assert window.tray is not None
    assert "Файл настроек" in log_text(window)
    assert "Файл настроек" in env.log_file()
    assert not window.service.schedule_active
    assert window.start_btn.isEnabled() and not window.stop_btn.isEnabled()
    assert window.max_size_spin.value() == 2


def test_active_tab_is_restored(env):
    ini = ("[General]\ntab_count=3\nactive_tab=1\n[Tab_0]\ntab_title=Первая\n"
           "[Tab_1]\ntab_title=Вторая\n[Tab_2]\ntab_title=Третья\n")
    window = env.window(ini)
    assert window.tabs_widget.count() == 3
    assert window.current_page().title == "Вторая"
    window.tabs_widget.setCurrentIndex(2)
    assert env.stored().active_tab == 2


# ------------------------------------------------------------ копирование
def test_manual_backup_copies_and_logs(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [src / "single.txt"], dst)
    window.manual_backup()
    assert window._running and not window.manual_btn.isEnabled() and not window.cancel_btn.isHidden()
    assert wait_backup(env, window)
    assert "✓ Успешно скопировано 3 файлов" in log_text(window)
    assert "Успешно скопировано 3 файлов" in env.log_file()
    assert len(list_rel(dst)) == 3
    assert window.manual_btn.isEnabled() and window.cancel_btn.isHidden()
    assert env.stored().last_backup_time is not None
    assert env.notifications[-1][0] == "info"
    assert env.dialogs == []


def test_manual_backup_without_sources_shows_dialog(env):
    window = env.window()
    window.manual_backup()
    assert env.dialogs and env.dialogs[0][0] == "warning"
    assert not window._running


def test_partial_result_is_a_warning(env, tree, monkeypatch):
    src, dst = tree
    real = copier_module.shutil.copy2

    def failing(source, target):
        if source.endswith("a.txt"):
            raise PermissionError("locked")
        return real(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", failing)
    window = env.window()
    fill_tab(window, [src / "docs"], [src / "single.txt"], dst)
    window.manual_backup()
    assert wait_backup(env, window)
    assert "⚠ Скопировано 2 файлов, ошибок: 1" in log_text(window)
    assert "Ошибка при копировании файла" in env.log_file()
    assert env.notifications[-1][0] == "warning"


def test_cancel_backup(env, tree, monkeypatch):
    src, dst = tree
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(20)})
    slow_copy(monkeypatch)
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.manual_backup()
    wait_for(env.app, lambda: list_rel(dst), timeout=5)
    window.cancel_backup()
    assert wait_backup(env, window)
    assert "✗ Операция отменена" in log_text(window)
    assert env.notifications[-1][0] == "warning"
    assert len(list_rel(dst)) < 22


# --------------------------------------------------------------- расписание
def test_scheduled_backup_runs_when_time_comes(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.start_schedule()
    service = window.service
    assert service.schedule_active
    assert env.stored().timer_active is True and env.stored().timer_started_at is not None
    assert not window.start_btn.isEnabled() and window.stop_btn.isEnabled()

    due = service.next_run
    service.tick(due + timedelta(seconds=1))
    assert service.next_run > due
    assert wait_backup(env, window)
    assert len(list_rel(dst)) == 2
    assert "Начато плановое копирование" in log_text(window)
    assert env.notifications[0][1] == "Резервное копирование"

    window.stop_schedule()
    assert not service.schedule_active and env.stored().timer_active is False
    assert "остановлено" in window.next_backup_label.text()


def test_scheduled_problems_never_open_dialogs(env, tree):
    src, dst = tree
    window = env.window()
    page = fill_tab(window, [src / "docs"], [], dst)
    window.start_schedule()
    window.copy_all_tabs_cb.setChecked(True)
    page.clear_folders()
    window.service.tick(window.service.next_run + timedelta(seconds=1))
    env.app.processEvents()
    assert env.dialogs == []
    assert not window._running
    assert "Плановое копирование не запущено" in log_text(window)
    assert env.notifications[-1][0] == "warning"


def test_scheduled_run_during_manual_run_is_skipped(env, tree, monkeypatch):
    src, dst = tree
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(8)})
    slow_copy(monkeypatch)
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.start_schedule()
    window.manual_backup()
    window.service.tick(window.service.next_run + timedelta(seconds=1))
    assert "уже выполняется" in log_text(window)
    assert wait_backup(env, window)
    assert len(list_rel(dst)) == 10
    assert log_text(window).count("Успешно скопировано") == 1


def test_changing_schedule_while_active_updates_label(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.time_edit.setTime(QTime(1, 0))
    window.start_schedule()
    before = window.service.next_run
    window.time_edit.setTime(QTime(23, 59))
    assert window.service.next_run != before
    assert window.service.next_run.hour == 23 and window.service.next_run.minute == 59
    assert "23:59" in window.next_backup_label.text()


# ------------------------------------------------ возобновление после запуска
def resume_ini(src, dst, extra="", tabs=None):
    tabs = tabs or f"[Tab_0]\nsource_folders={ini_path(src)}\ndestination_folder={ini_path(dst)}\ntab_title=Данные\n"
    return f"[General]\ntimer_active=true\nbackup_time=03:00\n{extra}\n{tabs}"


def test_resume_with_all_tabs_and_empty_last_tab(env, tree):
    src, dst = tree
    tabs = (f"[Tab_0]\nsource_folders={ini_path(src)}\ndestination_folder={ini_path(dst)}\ntab_title=Данные\n"
            "[Tab_1]\ntab_title=Пустая\n")
    window = env.window(resume_ini(src, dst, "copy_all_tabs=true\ntab_count=2\nactive_tab=1", tabs))
    assert window.service.schedule_active
    assert "Расписание возобновлено" in log_text(window)
    assert window.stop_btn.isEnabled() and "остановлено" not in window.next_backup_label.text()


def test_resume_impossible_without_sources(env):
    window = env.window("[General]\ntimer_active=true\n[Tab_0]\ntab_title=Пустая\n")
    assert not window.service.schedule_active
    assert "Расписание не возобновлено" in log_text(window)
    assert env.stored().timer_active is False


def test_missed_run_is_executed_after_start(env, tree):
    src, dst = tree
    started = "2000-01-01T00:00:00"
    window = env.window(resume_ini(src, dst, f"timer_started_at={started}"))
    assert "пропущено" in log_text(window)
    assert window.service.tick() is True
    assert wait_backup(env, window)
    assert len(list_rel(dst)) == 3
    assert env.stored().last_backup_time is not None


# ------------------------------------------------------------ трей и выход
def test_close_hides_to_tray_instead_of_quitting(env, monkeypatch):
    quits = []
    monkeypatch.setattr(env.app, "quit", lambda: quits.append(True))
    window = env.window()
    window.show()
    window.close()
    assert window.isHidden() and not window._quitting
    assert quits == []
    assert "свёрнуто в трей" in log_text(window)
    assert env.notifications[-1][1] == "Приложение работает в фоне"
    window.show()
    window.close()
    assert sum(1 for n in env.notifications if n[1] == "Приложение работает в фоне") == 1


def test_close_quits_when_tray_mode_disabled(env, monkeypatch):
    quits = []
    monkeypatch.setattr(env.app, "quit", lambda: quits.append(True))
    window = env.window()
    window.minimize_to_tray_cb.setChecked(False)
    window.show()
    window.close()
    assert window._quitting and quits == [True]
    assert env.stored().minimize_to_tray is False


def test_quit_keeps_schedule_for_next_start(env, tree, monkeypatch):
    src, dst = tree
    quits = []
    monkeypatch.setattr(env.app, "quit", lambda: quits.append(True))
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.start_schedule()
    window.quit_app()
    window.service.shutdown()
    assert quits == [True]
    assert env.stored().timer_active is True
    assert not window.tray.isVisible()
    assert "завершает работу" in env.log_file()


def test_show_from_tray_restores_window(env):
    window = env.window()
    window.hide_to_tray()
    assert window.isHidden()
    window.show_from_tray()
    assert not window.isHidden()


# ----------------------------------------------------------------- вкладки
def test_tab_management(env):
    window = env.window()
    window.add_new_tab()
    assert window.tabs_widget.count() == 2 and window.tabs_widget.currentIndex() == 1
    page = window.current_page()
    page.title_edit.setText("Очень длинное название вкладки")
    page._on_title_finished()
    assert window.tabs_widget.tabText(1) == "Очень длинн ..."
    assert env.stored().tabs[1].title == "Очень длинное название вкладки"
    window.close_tab(1)
    assert window.tabs_widget.count() == 1
    window.close_tab(0)
    assert window.tabs_widget.count() == 1
    assert len(env.stored().tabs) == 1


def test_missing_paths_are_shown_not_dropped(env, tmp_path):
    missing = ini_path(tmp_path / "нет такой папки")
    ini = f"[General]\ntab_count=1\n[Tab_0]\nsource_folders={missing}\ntab_title=USB\n"
    window = env.window(ini)
    page = window.current_page()
    assert page.to_config().folders == [missing]
    assert "недоступен" in page.folders_list.item(0).toolTip()
    assert env.stored().tabs[0].folders == [missing]


def test_system_folder_is_refused(env, tmp_path):
    window = env.window()
    page = window.current_page()
    system = system_paths()[0]
    assert page.add_folder_path(system) is False
    assert page.set_destination(system) is False
    assert page.to_config().folders == [] and page.destination == ""
    assert [call[1] for call in env.dialogs] == ["Папка не добавлена", "Папка не выбрана"]
    assert page.add_folder_path(str(tmp_path)) is True


# --------------------------------------------------------------- настройки
def test_autostart_failure_reverts_checkbox(env, monkeypatch):
    def broken():
        raise OSError("реестр недоступен")

    monkeypatch.setattr(autostart, "enable", broken)
    window = env.window()
    window.auto_start_cb.setChecked(True)
    assert not window.auto_start_cb.isChecked()
    assert env.dialogs and env.dialogs[-1][0] == "critical"
    assert env.stored().auto_start is False


def test_autostart_checkbox_calls_backend(env, monkeypatch):
    calls = []
    monkeypatch.setattr(autostart, "enable", lambda: calls.append("enable") or True)
    monkeypatch.setattr(autostart, "disable", lambda: calls.append("disable"))
    window = env.window()
    window.auto_start_cb.setChecked(True)
    window.auto_start_cb.setChecked(False)
    assert calls == ["enable", "disable"]


def test_perform_reset(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.add_new_tab()
    window.copy_all_tabs_cb.setChecked(True)
    window.start_schedule()
    window.perform_reset()
    assert env.stored() == AppConfig()
    assert window.tabs_widget.count() == 1 and not window.service.schedule_active
    assert window.start_btn.isEnabled() and not window.copy_all_tabs_cb.isChecked()


def test_settings_are_saved_on_change(env):
    window = env.window()
    window.period_type_combo.setCurrentText("Еженедельно")
    window.weekday_combo.setCurrentIndex(4)
    window.time_edit.setTime(QTime(21, 30))
    window.keep_history_cb.setChecked(False)
    window.max_size_spin.setValue(0)
    stored = env.stored()
    assert stored.period_type == "Еженедельно" and stored.weekday == 4
    assert stored.backup_time == "21:30" and stored.keep_history is False
    assert stored.max_file_size_gb == 0
