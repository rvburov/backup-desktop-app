"""Окно поверх настоящего бэкенда: команды уходят в сервис, события приходят обратно."""
import os
import time
from datetime import datetime, timedelta

import pytest
from PyQt5.QtCore import QCoreApplication, QEvent, QTime

from backup_app.backend import (NO_DESTINATION, NO_SOURCES, NO_TABS_WITH_DATA, PERIOD_MONTHLY, PERIOD_WEEKLY,
                                STATUS_OK, STATUS_PARTIAL, AppConfig, AppProblem, BackupFinished, BackupProgress,
                                BackupResult, BackupService, BackupStarted, ConfigChanged, HistoryAdded, HistoryEntry,
                                SettingsStore, setup_file_logging)
from backup_app.backend import autostart
from backup_app.backend import copier as copier_module
from backup_app.backend.safety import system_paths
from backup_app.frontend import constants as K
from backup_app.frontend import main_window as mw
from backup_app.frontend import widgets as W
from backup_app.frontend.bridge import ServiceBridge
from backup_app.frontend.tray import TrayIcon
from helpers import list_rel, make_tree, wait_for

SRC = {"docs": {"a.txt": "A", "sub": {"b.txt": "BB"}}, "single.txt": "S"}


class FakeMessageBox:
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
    """Окно с настоящим сервисом. Диалоги, тосты и уведомления записываются в списки."""
    FakeMessageBox.calls = []
    notifications = []
    toasts = []

    def fake_notify(_tray, title, message, kind="info", msecs=6000):
        notifications.append((kind, title, message))

    real_show = W.Toast.show_message

    def fake_toast(toast, title, text="", kind="info", timeout=W.Toast.TIMEOUT_MS):
        toasts.append((kind, title, text))
        real_show(toast, title, text, kind, timeout)

    monkeypatch.setattr(TrayIcon, "available", staticmethod(lambda: True))
    monkeypatch.setattr(TrayIcon, "notify", fake_notify)
    monkeypatch.setattr(W.Toast, "show_message", fake_toast)
    monkeypatch.setattr(mw, "QMessageBox", FakeMessageBox)
    # модальное окно отвечает сразу: ответ задает тест, вопросы записываются
    monkeypatch.setattr(W.OverlayDialog, "preset_answer", True)
    monkeypatch.setattr(W.OverlayDialog, "asked", [])
    created = []

    class Env:
        dialogs = FakeMessageBox.calls
        app = qapp
        dir = config_dir

        def ini(self):
            return config_dir / "settings.ini"

        def window(self, ini_text=None, show=False):
            if ini_text is not None:
                self.ini().write_text(ini_text, encoding="utf-8")
            log_path = setup_file_logging(str(config_dir / "logs"))
            service = BackupService(SettingsStore(str(self.ini())), missed_run_delay=0, log_path=log_path)
            bridge = ServiceBridge(service)
            window = mw.MainWindow(service, bridge)
            created.append((window, bridge, service))
            service.start(run_scheduler=False)
            if show:
                window.show()
                qapp.processEvents()
            return window

        def stored(self):
            return SettingsStore(str(self.ini())).load()

        def log_file(self):
            path = config_dir / "logs" / "backup-app.log"
            return path.read_text(encoding="utf-8") if path.exists() else ""

        @staticmethod
        def asked():
            return W.OverlayDialog.asked

    Env.notifications = notifications
    Env.toasts = toasts
    yield Env()
    for window, bridge, service in created:
        service.cancel()
        service.wait_idle(5)
        qapp.processEvents()
        bridge.close()
        window._quitting = True
        window.hide()
        if window.tray is not None:
            window.tray.hide()
        window.deleteLater()
    qapp.processEvents()
    # окна удаляются сразу: иначе они копятся, и каждая смена стиля в следующих тестах их перерисовывает
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def fill_tab(window, folders=(), files=(), destination=""):
    page = window.page
    for folder in folders:
        page.add_folder_path(str(folder))
    page.add_file_paths([str(path) for path in files])
    if destination:
        page.set_destination(str(destination))
    return page


def wait_backup(env, window):
    return wait_for(env.app, lambda: not window._running and not window.service.is_running)


def history_text(window):
    return window.history_panel.plain_text()


def ini_path(path):
    """В INI обратная косая черта экранируется, поэтому пути пишем с прямой."""
    return str(path).replace("\\", "/")


def tabs_ini(*titles, active=0, extra=""):
    parts = [f"[General]\ntab_count={len(titles)}\nactive_tab={active}\n{extra}\n"]
    for index, title in enumerate(titles):
        parts.append(f"[Tab_{index}]\ntab_id=uid{index:09d}\ntab_title={title}\n")
    return "".join(parts)


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
def test_fresh_start_has_empty_history_and_full_journal(env):
    window = env.window()
    assert window.windowTitle() == "Резервное копирование файлов"
    assert not window.windowIcon().isNull()
    assert len(window.tabs()) == 1 and window.tab_list.visible_count() == 1
    assert window.tray is not None
    assert history_text(window) == ""
    assert window.history_panel.empty_box.isVisibleTo(window.history_panel)
    assert "Файл настроек" in env.log_file()
    assert not window.service.schedule_active
    assert not window.page.schedule_switch.isChecked()
    assert window.settings_page.max_size_spin.value() == 2
    assert window.status_bar.pill.text() == "Следующее копирование: остановлено"
    assert window.status_bar.history_button.text() == "Свернуть историю"
    assert window.minimumWidth() >= 760 and window.minimumHeight() >= 560


def test_default_size_fits_the_screen(env):
    window = env.window()
    screen = env.app.primaryScreen().availableGeometry()
    assert window.width() <= max(760, int(screen.width() * 0.9))
    assert window.height() <= max(560, int(screen.height() * 0.9))


def test_active_tab_is_restored(env):
    window = env.window(tabs_ini("Первая", "Вторая", "Третья", active=1))
    assert len(window.tabs()) == 3
    assert window.page.title == "Вторая"
    assert window.tab_list.current_uid() == window.current_uid()
    window.select_tab(window.tabs()[2].uid)
    assert env.stored().active_tab == 2
    assert window.page.title == "Третья"


# ------------------------------------------------------------ копирование
def test_manual_backup_copies_and_logs(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [src / "single.txt"], dst)
    window.page.run_button.click()
    assert window._running == (window.current_uid(),)
    assert not window.page.run_button.isEnabled() and not window.page.delete_button.isEnabled()
    assert window.status_bar.is_running_shown() and not window.status_bar.cancel_button.isHidden()
    assert not window.sidebar.copy_all_button.isEnabled()
    assert window.page.status_line.text() == K.TAB_RUNNING_TEXT
    assert wait_backup(env, window)
    lines = history_text(window).splitlines()
    assert lines[0].endswith("  Ручное копирование: Без названия")
    assert lines[1].endswith("  ✓ Успешно скопировано 3 файла")
    assert "Успешно скопировано 3 файла" in env.log_file()
    assert len(list_rel(dst)) == 3
    assert window.page.run_button.isEnabled() and window.status_bar.cancel_button.isHidden()
    assert window.status_bar.is_result_shown()
    assert window.status_bar.result_label.text() == "Копирование завершено успешно"
    assert env.stored().tabs[0].last_backup_time is not None
    assert env.notifications[-1][:2] == ("info", "Копирование завершено")
    assert env.dialogs == [] and env.toasts == []


def test_manual_backup_without_sources_shows_toast(env):
    window = env.window(show=True)
    assert not window.page.run_button.isEnabled()
    assert window.manual_backup() == [NO_SOURCES, NO_DESTINATION]
    assert env.toasts[-1] == ("warn", "Ошибка", f"{K.NO_DATA_TEXT} {NO_SOURCES}; {NO_DESTINATION}")
    assert env.dialogs == []
    assert not window._running


def test_partial_result_is_a_warning(env, tree, monkeypatch):
    src, dst = tree
    real = copier_module.shutil.copy2

    def failing(source, target):
        if source.endswith("a.txt"):
            raise PermissionError(13, "Отказано в доступе")
        return real(source, target)

    monkeypatch.setattr(copier_module.shutil, "copy2", failing)
    window = env.window()
    fill_tab(window, [src / "docs"], [src / "single.txt"], dst)
    window.manual_backup()
    assert wait_backup(env, window)
    history = history_text(window)
    assert "⚠ Скопировано 2 файла, ошибок: 1" in history
    assert "a.txt: нет доступа" in history and "Отказано в доступе" not in history
    assert "Отказано в доступе" in env.log_file()
    assert env.notifications[-1][0] == "warning"
    assert window.status_bar.result_label.text() == "Копирование завершено с ошибками"


def test_cancel_backup(env, tree, monkeypatch):
    src, dst = tree
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(20)})
    slow_copy(monkeypatch)
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.manual_backup()
    wait_for(env.app, lambda: list_rel(dst), timeout=5)
    window.status_bar.cancel_button.click()
    assert window.status_bar.run_label.text() == K.CANCELLING_TEXT
    assert wait_backup(env, window)
    assert "✗ Операция отменена" in history_text(window)
    assert env.notifications[-1][0] == "warning"
    assert len(list_rel(dst)) < 22


def test_second_manual_run_is_refused_with_toast(env, tree, monkeypatch):
    src, dst = tree
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(10)})
    slow_copy(monkeypatch)
    window = env.window(show=True)
    fill_tab(window, [src / "docs"], [], dst)
    window.manual_backup()
    assert window.copy_all_tabs() == [mw.ALREADY_RUNNING]
    assert env.toasts[-1] == ("info", "Копирование", mw.ALREADY_RUNNING)
    window.cancel_backup()
    assert wait_backup(env, window)


def test_copy_all_tabs_runs_every_tab_with_data(env, tmp_path, monkeypatch):
    first, second, dst = tmp_path / "one", tmp_path / "two", tmp_path / "dst"
    make_tree(first, {"a.txt": "A"})
    make_tree(second, {"b.txt": "B"})
    dst.mkdir()
    window = env.window()
    window.page.rename("Первая")
    fill_tab(window, [first], [], dst)
    window.add_new_tab()
    window.page.rename("Вторая")
    fill_tab(window, [second], [], dst)
    window.add_new_tab()  # пустая вкладка молча пропускается
    window.sidebar.copy_all_button.click()
    assert window.status_bar.run_label.text() == K.PREPARING_TEXT
    assert wait_backup(env, window)
    assert "Ручное копирование: Первая, Вторая" in history_text(window)
    assert sorted(list_rel(dst)) == ["one/a.txt", "two/b.txt"] or len(list_rel(dst)) == 2
    assert env.toasts == []


def test_copy_all_tabs_without_data_explains(env):
    window = env.window(show=True)
    assert window.copy_all_tabs() == [NO_TABS_WITH_DATA]
    assert env.toasts[-1] == ("warn", "Ошибка", f"{K.NO_DATA_TEXT} {NO_TABS_WITH_DATA}")


# --------------------------------------------------------------- расписание
def test_schedule_switch_on_refused_and_off(env, tree):
    src, dst = tree
    window = env.window(show=True)
    switch = window.page.schedule_switch
    switch.click()  # без данных расписание не запускается
    assert not switch.isChecked() and not window.service.schedule_active
    assert env.toasts[-1] == ("warn", "Расписание не запущено",
                              f"{K.NO_DATA_TEXT} {NO_SOURCES}; {NO_DESTINATION}")
    assert window.page.schedule_off_note.isVisibleTo(window.page)
    fill_tab(window, [src / "docs"], [], dst)
    switch.click()
    assert switch.isChecked() and window.service.schedule_active
    assert window.page.schedule_box.isVisibleTo(window.page)
    assert window.page.next_label.text().startswith("Следующее копирование: ")
    assert window.tab_list.entry(window.current_uid()).status == W.STATUS_ON
    assert window.tab_list.entry(window.current_uid()).sub == "Каждый день · 09:00"
    switch.click()
    assert not switch.isChecked() and not window.service.schedule_active
    assert window.tab_list.entry(window.current_uid()).sub == "Расписание остановлено"
    assert history_text(window).splitlines()[-1].endswith("  Расписание остановлено: Без названия")


def test_scheduled_backup_runs_when_time_comes(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    assert window.set_schedule(True)
    service = window.service
    assert service.schedule_active
    stored = env.stored().tabs[0]
    assert stored.schedule_on is True and stored.timer_started_at is not None
    assert window.page.schedule_switch.isChecked()
    assert "Расписание запущено: Без названия, следующее копирование:" in history_text(window)

    due = service.next_run
    service.tick(due + timedelta(seconds=1))
    assert service.next_run > due
    assert wait_backup(env, window)
    assert len(list_rel(dst)) == 2
    assert "Плановое копирование: Без названия" in history_text(window)
    assert env.notifications[0][1:] == ("Резервное копирование", "Начато плановое копирование: Без названия")

    window.set_schedule(False)
    assert not service.schedule_active and env.stored().tabs[0].schedule_on is False
    assert window.status_bar.pill.text() == "Следующее копирование: остановлено"
    assert history_text(window).splitlines()[-1].endswith("  Расписание остановлено: Без названия")


def test_scheduled_problems_never_open_dialogs(env, tree):
    src, dst = tree
    window = env.window()
    page = fill_tab(window, [src / "docs"], [], dst)
    window.set_schedule(True)
    page.clear_sources()
    assert window.tab_list.entry(window.current_uid()).status == W.STATUS_WARN
    assert window.status_bar.pill.text() == "Следующее копирование: остановлено"
    window.service.tick(window.service.next_run + timedelta(seconds=1))
    env.app.processEvents()
    assert env.dialogs == [] and env.toasts == []
    assert not window._running
    assert "✗ Плановое копирование не запущено" in history_text(window)
    assert env.notifications[-1][0] == "warning"


def test_scheduled_run_during_manual_run_is_skipped(env, tree, monkeypatch):
    src, dst = tree
    make_tree(src / "docs", {f"f{i:02d}.txt": "x" for i in range(8)})
    slow_copy(monkeypatch)
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.set_schedule(True)
    window.manual_backup()
    window.service.tick(window.service.next_run + timedelta(seconds=1))
    assert "⚠ Плановое копирование не запущено: в это время шло другое копирование" in history_text(window)
    assert wait_backup(env, window)
    assert len(list_rel(dst)) == 10
    assert history_text(window).count("Успешно скопировано") == 1


def test_changing_schedule_while_active_updates_labels(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.page.time_edit.setTime(QTime(1, 0))
    window.set_schedule(True)
    before = window.service.next_run
    window.page.time_edit.setTime(QTime(23, 59))
    assert window.service.next_run != before
    assert window.service.next_run.hour == 23 and window.service.next_run.minute == 59
    assert "23:59" in window.page.next_label.text()
    assert "23:59" in window.page.status_line.text()
    assert window.status_bar.pill.text().endswith("в 23:59 · Без названия")
    assert window.tray.next_action.text() == (
        f"Следующее копирование: {window.service.next_run:%d.%m.%Y %H:%M} · Без названия")


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
    assert "Расписание возобновлено" in env.log_file() and "возобновлено" not in history_text(window)
    assert window.status_bar.pill.text().startswith("Следующее копирование: ")
    assert window.status_bar.pill.text().endswith(" · Данные")
    first, second = (window.tab_list.entry(tab.uid) for tab in window.tabs())
    assert first.status == W.STATUS_ON and first.sub == "Каждый день · 03:00"
    assert second.status == W.STATUS_WARN and second.sub == NO_SOURCES
    assert window.page.title == "Пустая" and not window.page.schedule_switch.isChecked()


def test_resume_impossible_without_sources(env):
    window = env.window("[General]\ntimer_active=true\n[Tab_0]\ntab_title=Пустая\n")
    assert not window.service.schedule_active
    assert "✗ Расписание не возобновлено" in history_text(window)
    assert env.stored().tabs[0].schedule_on is False
    assert not window.page.schedule_switch.isChecked()


def test_missed_run_is_executed_after_start(env, tree):
    src, dst = tree
    started = "2000-01-01T00:00:00"
    window = env.window(resume_ini(src, dst, f"timer_started_at={started}"))
    assert "⚠ Пропущено плановое копирование" in history_text(window)
    assert window.service.tick() is True
    assert wait_backup(env, window)
    assert len(list_rel(dst)) == 3
    assert "Плановое копирование: Данные" in history_text(window)
    assert env.stored().tabs[0].last_backup_time is not None


# ------------------------------------------------------------ трей и выход
def test_close_hides_to_tray_instead_of_quitting(env, monkeypatch):
    quits = []
    monkeypatch.setattr(env.app, "quit", lambda: quits.append(True))
    window = env.window()
    window.show()
    window.close()
    assert window.isHidden() and not window._quitting
    assert quits == []
    assert "свернуто в трей" in env.log_file() and "трей" not in history_text(window)
    assert env.notifications[-1][1] == "Приложение работает в фоне"
    window.show()
    window.close()
    assert sum(1 for n in env.notifications if n[1] == "Приложение работает в фоне") == 1


def test_close_quits_when_tray_mode_disabled(env, monkeypatch):
    quits = []
    monkeypatch.setattr(env.app, "quit", lambda: quits.append(True))
    window = env.window()
    window.settings_page.set_checked("minimize_to_tray", False)
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
    window.set_schedule(True)
    window.tray.quit_action.trigger()
    window.service.shutdown()
    assert quits == [True]
    assert env.stored().tabs[0].schedule_on is True
    assert not window.tray.isVisible()
    assert "завершает работу" in env.log_file()


def test_show_from_tray_restores_window(env):
    window = env.window()
    window.hide_to_tray()
    assert window.isHidden()
    window.tray.open_action.trigger()
    assert not window.isHidden()


def test_tray_menu_texts_tooltip_and_copy_all(env, tree):
    src, dst = tree
    window = env.window()
    tray = window.tray
    assert tray.menu_texts() == ["Открыть окно", "Копировать все вкладки", "",
                                 "Следующее копирование: остановлено", "", "Выход"]
    assert not tray.next_action.isEnabled()
    assert tray.toolTip() == "Резервное копирование файлов\nСледующее копирование: остановлено"
    window.page.rename("Документы")
    fill_tab(window, [src / "docs"], [], dst)
    window.set_schedule(True)
    text = f"Следующее копирование: {window.service.next_run:%d.%m.%Y %H:%M} · Документы"
    assert tray.next_action.text() == text
    assert tray.toolTip() == f"Резервное копирование файлов\n{text}"
    tray.backup_action.trigger()
    assert window._running and not tray.backup_action.isEnabled()
    assert wait_backup(env, window)
    assert tray.backup_action.isEnabled()
    assert "Ручное копирование: Документы" in history_text(window)


def test_tray_copy_all_refusal_goes_to_tray_when_hidden(env):
    window = env.window()
    window.hide()
    window.tray.backup_action.trigger()
    assert env.toasts == []
    assert env.notifications[-1] == ("warning", "Ошибка", f"{K.NO_DATA_TEXT} {NO_TABS_WITH_DATA}")


# ----------------------------------------------------------------- вкладки
def test_tab_management_rename_and_delete(env):
    window = env.window()
    first = window.current_uid()
    window.sidebar.add_button.click()
    assert len(window.tabs()) == 2 and window.current_uid() != first
    uid = window.current_uid()
    long_name = "Очень длинное название вкладки"
    window.page.rename(long_name)
    assert window.tab_list.entry(uid).name == long_name
    assert window.page.scope_badge.text() == f"действуют только для «{long_name}»"
    assert window.history_panel.filter_check.text() == f"Только «{long_name}»"
    assert env.stored().tabs[1].title == long_name

    W.OverlayDialog.preset_answer = False
    assert window.ask_delete_tab() is False and len(window.tabs()) == 2
    assert env.asked()[-1] == (f"Удалить вкладку «{long_name}»?", K.DELETE_TEXT)
    W.OverlayDialog.preset_answer = True
    window.page.delete_button.click()
    assert len(window.tabs()) == 1 and window.current_uid() == first
    assert len(env.stored().tabs) == 1
    asked = len(env.asked())
    assert not window.page.delete_button.isEnabled()
    assert window.ask_delete_tab() is False and len(env.asked()) == asked  # последнюю не удалить


def test_running_tab_cannot_be_deleted(env):
    window = env.window(tabs_ini("A", "B"))
    uid = window.current_uid()
    window.on_backend_event(BackupStarted(False, ("A",), (uid,)))
    assert not window.page.delete_button.isEnabled()
    assert window.ask_delete_tab() is False and env.asked() == []
    window.on_backend_event(BackupFinished(BackupResult(status=STATUS_OK, message="ok"), False, (uid,)))
    assert window.page.delete_button.isEnabled()


def test_title_typing_is_saved_after_pause(env):
    window = env.window()
    uid = window.current_uid()
    edit = window.page.title_edit.line_edit
    edit.setText("Фото")
    edit.textEdited.emit("Фото")
    assert window.tab_list.entry(uid).name == "Фото"
    assert window.history_panel.filter_check.text() == "Только «Фото»"
    assert env.stored().tabs[0].title == "Без названия"   # сохраняется после паузы
    assert wait_for(env.app, lambda: env.stored().tabs[0].title == "Фото", timeout=3)
    edit.setText("")
    edit.textEdited.emit("")
    assert window.tab_list.entry(uid).name == "Без названия"
    window.add_new_tab()  # смена вкладки сохраняет набранное сразу
    assert env.stored().tabs[0].title == "Без названия"


def test_search_filters_tabs_and_shows_count(env):
    names = ["Документы", "Фото", "Проекты", "Музыка", "Видео", "Почта"]
    window = env.window(tabs_ini(*names))
    assert not window.sidebar.search_box.isVisibleTo(window.sidebar)
    assert window.sidebar.count_label.text() == "6"
    window.add_new_tab()
    assert window.sidebar.search_box.isVisibleTo(window.sidebar)
    assert window.sidebar.count_label.text() == "7"
    window.sidebar.search.setText("фо")
    assert window.tab_list.visible_count() == 1
    assert window.sidebar.count_label.text() == "1 из 7"
    window.sidebar.search.setText("нет такой")
    assert window.tab_list.visible_count() == 0 and window.tab_list._empty_text == "Нет вкладок с «нет такой»"
    window.add_new_tab()  # новая вкладка сбрасывает поиск
    assert window.sidebar.search.text() == "" and window.sidebar.count_label.text() == "8"


def test_switching_between_many_tabs_is_fast(env):
    window = env.window(tabs_ini(*[f"Вкладка {i}" for i in range(500)]))
    uids = [tab.uid for tab in window.tabs()]
    started = time.monotonic()
    for uid in uids[:40]:
        window.select_tab(uid)
    assert time.monotonic() - started < 8
    assert window.page.title == "Вкладка 39"


def test_config_changed_keeps_current_tab(env):
    window = env.window(tabs_ini("A", "B", "C"))
    uid = window.tabs()[2].uid
    window.select_tab(uid)
    window.on_backend_event(ConfigChanged(window.service.config))
    assert window.current_uid() == uid and window.page.title == "C"
    assert window.tab_list.current_uid() == uid


def test_missing_paths_are_shown_not_dropped(env, tmp_path):
    missing = ini_path(tmp_path / "нет такой папки")
    ini = f"[General]\ntab_count=1\n[Tab_0]\nsource_folders={missing}\ntab_title=USB\n"
    window = env.window(ini)
    page = window.page
    assert page.to_config().folders == [missing]
    assert "недоступен" in page.source_tooltips()[0]
    assert page.source_list.rows()[0][2]
    assert page.summary_label.text() == "1 папка · недоступно: 1"
    assert env.stored().tabs[0].folders == [missing]


def test_system_folder_is_refused_with_notice(env, tmp_path):
    window = env.window(tabs_ini("A", "B"))
    page = window.page
    system = system_paths()[0]
    assert page.add_folder_path(system) is False
    assert page.notice_visible() and page.notice.title() == "Папка не добавлена"
    assert system in page.notice.text()
    assert page.set_destination(system) is False
    assert page.notice.title() == "Папка не выбрана"
    assert page.add_file_paths([system]) == 0 and page.notice.title() == "Файлы не добавлены"
    assert page.to_config().folders == [] and page.destination == ""
    assert env.dialogs == [] and env.toasts == []
    page.notice.close_button.click()
    assert not page.notice_visible()
    page.add_folder_path(system)
    window.select_tab(window.tabs()[1].uid)  # смена вкладки скрывает плашку
    assert not page.notice_visible()
    assert page.add_folder_path(str(tmp_path)) is True


def test_sources_list_and_preview(env, tree):
    src, dst = tree
    window = env.window()
    page = fill_tab(window, [src / "docs"], [src / "single.txt"], dst)
    assert page.summary_label.text() == "1 папка, 1 файл"
    assert [row[0] for row in page.source_list.rows()] == ["folder", "file"]
    path = page.preview_path.text()
    assert path.endswith("/docs/Отчет.docx") and "Резервное копирование " in path
    page.contents_option.checkbox.click()
    assert page.preview_path.text().endswith(" " + datetime.now().strftime("%d-%m-%Y") + "/Отчет.docx")
    assert env.stored().tabs[0].copy_folder_contents is True
    page.remove_path(str(src / "docs"))
    assert page.summary_label.text() == "1 файл"
    assert page.preview_path.text().endswith("/single.txt")
    page.clear_button.click()
    assert page.summary_label.text() == "пока ничего не выбрано"
    assert page.empty_box.isVisibleTo(page) and not page.clear_button.isEnabled()
    assert env.stored().tabs[0].files == []


# --------------------------------------------------------------- настройки
def test_autostart_failure_reverts_switch(env, monkeypatch):
    def broken():
        raise OSError("реестр недоступен")

    monkeypatch.setattr(autostart, "enable", broken)
    window = env.window()
    window.settings_page.set_checked("auto_start", True)
    assert not window.settings_page.value("auto_start")
    assert env.dialogs and env.dialogs[-1][0] == "critical"
    assert env.stored().auto_start is False


def test_autostart_switch_calls_backend(env, monkeypatch):
    calls = []
    monkeypatch.setattr(autostart, "enable", lambda: calls.append("enable") or True)
    monkeypatch.setattr(autostart, "disable", lambda: calls.append("disable"))
    window = env.window()
    window.settings_page.set_checked("auto_start", True)
    window.settings_page.set_checked("auto_start", False)
    assert calls == ["enable", "disable"]


def test_settings_page_switches_and_max_size_are_saved(env):
    window = env.window()
    window.sidebar.settings_button.click()
    assert window.current_view() == "settings" and window.tab_list.current_uid() is None
    window.settings_page.set_checked("show_notifications", False)
    window.settings_page.set_checked("run_missed", False)
    window.settings_page.max_size_spin.setValue(0)
    stored = env.stored()
    assert stored.show_notifications is False and stored.run_missed is False
    assert stored.max_file_size_gb == 0
    window.select_tab(window.current_uid())
    assert window.current_view() == "tab"


def test_perform_reset(env, tree):
    src, dst = tree
    window = env.window()
    fill_tab(window, [src / "docs"], [], dst)
    window.set_schedule(True)
    window.add_new_tab()
    window.perform_reset()
    stored, default = env.stored(), AppConfig()
    assert len(stored.tabs) == 1 and stored.tabs[0].title == default.tabs[0].title
    assert stored.tabs[0].keep_history and stored.tabs[0].create_backup_folder
    assert not stored.tabs[0].copy_folder_contents and not stored.tabs[0].folders
    assert stored.max_file_size_gb == default.max_file_size_gb
    assert len(window.tabs()) == 1 and not window.service.schedule_active
    assert not window.page.schedule_switch.isChecked()
    assert "Расписание остановлено: настройки сброшены" in history_text(window)


def test_reset_flow_asks_and_stays_on_settings(env):
    window = env.window(tabs_ini("A", "B"), show=True)
    window.show_settings_section()
    W.OverlayDialog.preset_answer = False
    window.settings_page.reset_button.click()
    assert env.asked()[-1] == (K.RESET_TITLE, K.RESET_TEXT)
    assert len(window.tabs()) == 2 and env.toasts == []
    W.OverlayDialog.preset_answer = True
    window.settings_page.reset_button.click()
    assert len(window.tabs()) == 1 and window.current_view() == "settings"
    assert env.toasts[-1] == ("info", "Сброс завершен", "Все настройки успешно сброшены к значениям по умолчанию.")


def test_tab_settings_are_saved_on_change(env):
    window = env.window()
    page = window.page
    page.period.button(PERIOD_WEEKLY).click()
    page.day_chips.button(4).click()
    page.time_edit.setTime(QTime(21, 30))
    page.date_name_option.checkbox.click()
    stored = env.stored().tabs[0]
    assert stored.period_type == PERIOD_WEEKLY and stored.weekday == 4
    assert stored.backup_time == "21:30" and stored.keep_history is False
    page.period.button(PERIOD_MONTHLY).click()
    for _ in range(30):
        page.monthday.up_button.click()
    assert env.stored().tabs[0].monthday == 31
    assert not page.month_hint.isHidden()


def test_splitter_limits_and_reset(env):
    window = env.window(show=True)
    splitter = window.splitter
    window.resize(1180, 868)
    env.app.processEvents()
    assert splitter.side_width() == 240
    assert splitter.set_side_width(100) == 180
    assert splitter.set_side_width(1000) == 440
    splitter.reset_side_width()
    assert splitter.side_width() == 240
    assert window.stack.minimumWidth() == 380


# -------------------------------------------------------- состояние копирования
def test_running_subline_and_status_bar_states(env):
    window = env.window(tabs_ini("A", "B", "C"))
    a, b, _c = (tab.uid for tab in window.tabs())
    on = window.on_backend_event
    on(BackupStarted(False, ("A",), (a,)))
    assert window.tab_list.entry(a).status == W.STATUS_RUNNING
    assert window.tab_list.entry(a).sub == "Подготовка к копированию..."
    bar = window.status_bar
    assert bar.run_label.text() == "Подготовка к копированию..." and bar.progress.is_indeterminate()
    assert bar.detail_label.isHidden()
    on(BackupProgress(0, "Начинаем копирование (10.0 MB)"))
    assert bar.run_label.text() == "Копирование «A»" and not bar.progress.is_indeterminate()
    on(BackupProgress(40, "Копирование... (4.0 MB / 10.0 MB) | Файлов: 3"))
    assert window.tab_list.entry(a).sub == "Копирование... 40%"
    assert bar.progress.value() == 40 and bar.detail_label.text().startswith("Копирование... (4.0 MB")
    on(BackupFinished(BackupResult(status=STATUS_PARTIAL, message="Скопировано 3 файла, ошибок: 1"), False, (a,)))
    assert bar.is_result_shown() and bar.result_label.text() == "Копирование завершено с ошибками"
    assert bar.result_icon.text() == "⚠"
    window._flash_timer.timeout.emit()
    assert not bar.is_result_shown() and not bar.is_running_shown()

    on(BackupStarted(False, ("A", "B"), (a, b)))
    on(BackupProgress(0, "Начинаем копирование (1.0 MB)"))
    assert bar.run_label.text() == "Копирование 2 вкладок"
    on(BackupProgress(50, "Копирование вкладки 'B'..."))
    assert bar.run_label.text() == "Копирование вкладки 'B'..."
    assert window.tab_list.entry(b).sub == "Копирование... 50%"
    on(BackupFinished(BackupResult(status=STATUS_OK, message="ok"), False, (a, b)))
    assert window.tab_list.entry(a).status == W.STATUS_WARN


def test_status_pill_shows_nearest_schedule(env, tmp_path):
    folder = ini_path(tmp_path)
    window = env.window(tabs_ini("A", "B"))
    a, b = window.tabs()
    for tab, time_text in ((a, "23:58"), (b, "23:59")):
        window.select_tab(tab.uid)
        window.page.add_folder_path(folder)
        window.page.set_destination(folder)
        window.page.time_edit.setTime(QTime.fromString(time_text, "hh:mm"))
        assert window.set_schedule(True)
    nearest = min(window.service.next_runs().values())
    when = mw.fmt_when(nearest, datetime.now())
    assert window.status_bar.pill.text() == f"Следующее копирование: {when} · A"
    assert window.page.status_line.text() == "Следующее копирование: " + mw.fmt_when(
        window.service.next_runs()[b.uid], datetime.now())


# -------------------------------------------------------- история копирования
def history_file(env, entries):
    (env.dir / "history.txt").write_text("".join("\n".join(e.file_lines()) + "\n" for e in entries),
                                         encoding="utf-8")


def test_history_from_previous_runs_is_shown_at_start(env):
    recent = datetime.now() - timedelta(days=1)
    old = datetime.now() - timedelta(days=400)
    (env.dir / "history.txt").write_text(
        f"{old:%d.%m.%Y %H:%M}  ✓ Старое копирование\n"
        f"{recent:%d.%m.%Y %H:%M}  ⚠ Скопировано 2 файла, ошибок: 1\n"
        "                    Не скопирован C:/Документы/отчет.docx: файл занят другой программой\n",
        encoding="utf-8")
    window = env.window()
    lines = history_text(window).splitlines()
    assert len(lines) == 2
    assert lines[0] == f"{recent:%d.%m.%Y %H:%M}  ⚠ Скопировано 2 файла, ошибок: 1"
    assert lines[1].strip() == "Не скопирован C:/Документы/отчет.docx: файл занят другой программой"
    assert window.status_bar.history_button.text() == "Свернуть историю"
    window.status_bar.history_button.click()
    assert window.history_panel.isHidden()
    assert window.status_bar.history_button.text() == "История копирования (1)"
    window.status_bar.history_button.click()
    assert not window.history_panel.isHidden()


def test_history_filter_by_tab(env):
    now = datetime.now().replace(second=0, microsecond=0)
    history_file(env, [HistoryEntry(now, "Ручное копирование: A", (), ("uid000000000",)),
                       HistoryEntry(now, "Ручное копирование: B", (), ("uid000000001",)),
                       HistoryEntry(now, "Расписание остановлено: настройки сброшены")])
    window = env.window(tabs_ini("A", "B"))
    panel = window.history_panel
    assert len(panel.visible_entries()) == 3
    assert panel.filter_check.text() == "Только «A»"
    panel.set_only_tab(True)
    assert [e.text for e in panel.visible_entries()] == ["Ручное копирование: A"]
    window.select_tab("uid000000001")
    assert panel.filter_check.text() == "Только «B»"
    assert [e.text for e in panel.visible_entries()] == ["Ручное копирование: B"]
    window.on_backend_event(HistoryAdded(HistoryEntry(now, "✓ Готово", (), ("uid000000001",))))
    window.on_backend_event(HistoryAdded(HistoryEntry(now, "✓ Чужое", (), ("uid000000000",))))
    assert [e.text for e in panel.visible_entries()] == ["Ручное копирование: B", "✓ Готово"]
    panel.set_only_tab(False)
    assert len(panel.visible_entries()) == 5
    assert panel.total_count() == 5


def test_history_keeps_a_line_limit(env, monkeypatch):
    from backup_app.frontend import history_panel
    monkeypatch.setattr(history_panel, "HISTORY_VIEW_LIMIT", 5)
    window = env.window()
    now = datetime.now()
    for index in range(4):
        window.on_backend_event(HistoryAdded(HistoryEntry(now, f"Запись {index}", ("подробность",))))
    texts = [e.text for e in window.history_panel.visible_entries()]
    assert texts == ["Запись 2", "Запись 3"]


def test_journal_button_opens_log_file(env, monkeypatch):
    opened = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url):
            opened.append(url.toLocalFile())
            return True

    monkeypatch.setattr(mw, "QDesktopServices", FakeDesktop)
    window = env.window()
    window.history_panel.journal_button.click()
    assert [os.path.normpath(path) for path in opened] == [os.path.normpath(window.service.log_path)]


def test_journal_button_without_journal_explains(env, monkeypatch):
    window = env.window(show=True)
    monkeypatch.setattr(window.service, "_log_path", None)
    window.history_panel.journal_button.click()
    assert env.toasts[-1] == ("info", "Подробный журнал", "Журнал пока пуст.")
    assert window.toast.isVisible()


def test_app_problem_shows_dialog_or_tray_notification(env):
    window = env.window()
    window.show()
    window.service._emit(AppProblem("Не удалось сохранить настройки", "диск защищен от записи"))
    assert env.dialogs[-1] == ("warning", "Не удалось сохранить настройки", "диск защищен от записи")
    window.settings_page.set_checked("show_notifications", False)
    window.hide()
    window.service._emit(AppProblem("Не удалось проверить автозапуск", "нет доступа"))
    assert env.notifications[-1] == ("warning", "Не удалось проверить автозапуск", "нет доступа")
