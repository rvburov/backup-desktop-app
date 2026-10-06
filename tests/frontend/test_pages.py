"""Тексты страницы вкладки, пример копии, история и раскладка с переносом — без сервиса."""
import os
from datetime import datetime

import pytest
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QPushButton, QWidget

from backup_app.backend import (NO_DESTINATION, NO_SOURCES, PATH_SYSTEM, PATH_UNAVAILABLE, PERIOD_MONTHLY,
                                PERIOD_WEEKLY, HistoryEntry, TabConfig, backup_folder_name, folder_copy_name)
from backup_app.frontend import theme
from backup_app.frontend import widgets as W
from backup_app.frontend.history_panel import HistoryPanel, split_icon
from backup_app.frontend.tab_page import (TabPage, fmt_when, preview_texts, problem_line, sched_short, tab_name,
                                          tab_problem)

NOW = datetime(2026, 10, 6, 14, 38, 3)  # вторник


@pytest.fixture
def themed(qapp):
    theme.apply(qapp)
    yield qapp
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_fmt_when():
    assert fmt_when(datetime(2026, 10, 6, 18, 0), NOW) == "сегодня в 18:00"
    assert fmt_when(datetime(2026, 10, 7, 9, 0), NOW) == "завтра в 09:00"
    assert fmt_when(datetime(2026, 10, 11, 22, 0), NOW) == "вс, 11.10 в 22:00"
    assert fmt_when(datetime(2026, 11, 1, 22, 0), NOW) == "вс, 01.11 в 22:00"


def test_sched_short_and_names():
    tab = TabConfig(title="  ", backup_time="09:00")
    assert tab_name(tab) == "Без названия"
    assert sched_short(tab, False) == "Расписание остановлено"
    assert sched_short(tab, True) == "Каждый день · 09:00"
    tab.period_type, tab.weekday, tab.backup_time = PERIOD_WEEKLY, 6, "22:00"
    assert sched_short(tab, True) == "По воскресеньям · 22:00"
    tab.period_type, tab.monthday, tab.backup_time = PERIOD_MONTHLY, 1, "18:00"
    assert sched_short(tab, True) == "1-го числа · 18:00"
    assert tab_problem(tab) == NO_SOURCES
    tab.files = ["C:/a.txt"]
    assert tab_problem(tab) == NO_DESTINATION
    tab.destination = "D:/Backup"
    assert tab_problem(tab) == ""


def test_problem_line():
    assert problem_line("F:/Камера", PATH_UNAVAILABLE) == "F:/Камера — недоступен, будет пропущен"
    assert problem_line("C:/Windows", PATH_SYSTEM) == "C:/Windows — системный путь, будет пропущен"


def test_preview_follows_copier_naming():
    tab = TabConfig(destination="D:/Backup/Документы", folders=["C:/Users/user/Documents"])
    path, note = preview_texts(tab, NOW, [("folder", "C:/Users/user/Documents")])
    assert path == f"D:/Backup/Документы/{backup_folder_name(NOW)}/Documents/Отчет.docx"
    assert backup_folder_name(NOW) == "Резервное копирование 06-10-2026"
    assert note == ("Ничего не перезаписывается: если папка «Documents» уже есть, копия получит имя "
                    "Documents_06.10.2026_14-38-03. Папка с датой одна на день: повторные копирования в тот же "
                    "день попадают в нее.")
    # только содержимое папок, без папки с датой и без даты в имени: файлы — прямо в папку назначения
    tab.copy_folder_contents, tab.create_backup_folder, tab.keep_history = True, False, False
    path, note = preview_texts(tab, NOW, [("folder", "C:/Users/user/Documents")])
    assert path == "D:/Backup/Документы/Отчет.docx"
    assert note == "Ничего не перезаписывается: если файл «Отчет.docx» уже есть, копия получит имя Отчет_(1).docx"
    # первый доступный источник — файл
    tab.copy_folder_contents = False
    path, note = preview_texts(tab, NOW, [("file", "C:/Users/user/Desktop/Пароли.kdbx")])
    assert path == "D:/Backup/Документы/Пароли.kdbx"
    assert note.endswith("копия получит имя Пароли_(1).kdbx")
    # корень диска копируется в папку «Диск_C», как в copier
    path, _note = preview_texts(tab, NOW, [("folder", "C:/")])
    assert path == f"D:/Backup/Документы/{folder_copy_name('C:/')}/Отчет.docx"
    assert preview_texts(TabConfig(), NOW, []) == ("Сначала выберите папку назначения",
                                                   "Существующие файлы никогда не перезаписываются.")


def test_tab_page_shows_problem_paths(themed):
    class Validator:
        @staticmethod
        def path_problem(path):
            return PATH_UNAVAILABLE if path.startswith("F:") else None

        @staticmethod
        def source_problem(path):
            return None

        destination_problem = source_problem

    page = TabPage(Validator())
    tab = TabConfig(title="Фото", folders=["C:/Pictures", "F:/Камера"], files=["C:/a.txt"], destination="E:/Фото")
    page.bind(tab)
    assert page.summary_label.text() == "2 папки, 1 файл · недоступно: 1"
    assert page.source_tooltips()[1] == f"F:/Камера\n{PATH_UNAVAILABLE}"
    page.set_state(True, datetime(2026, 10, 11, 22, 0), False, False, True, NOW)
    assert page.status_line.tone == "ok"
    assert page.status_line.text() == "Следующее копирование: вс, 11.10 в 22:00"
    assert page.scope_badge.text() == "действуют только для «Фото»"
    page.set_state(False, None, False, False, True, NOW)
    assert page.status_line.text() == "Следующее копирование: остановлено — только ручной запуск"
    page.set_state(False, None, True, True, False, NOW)
    assert page.status_line.tone == "run" and not page.run_button.isEnabled()
    assert not page.delete_button.isEnabled()
    page.deleteLater()


def test_source_list_scrolls_only_when_rows_do_not_fit(themed):
    from backup_app.frontend.tab_page import SourceDelegate, SourceList
    view = SourceList()
    view.resize(600, 300)
    view.show()
    for count, height in ((1, 47), (2, 93), (3, 140), (4, 186), (5, 188), (8, 188)):
        view.set_sources([("folder", f"C:/Папка {i}", "") for i in range(count)])
        QCoreApplication.processEvents()
        bar = view.verticalScrollBar()
        assert view.height() == height                          # строки макета по 46.6 px, не больше 188
        assert bar.isVisible() == (count > 4), count            # полоса — только когда строки не помещаются
        rows = [view.visualRect(view.model_.index(i, 0)) for i in range(min(count, 4))]
        assert [r.top() - rows[0].top() for r in rows] == [SourceDelegate.rows_height(i) for i in range(len(rows))]
        if count <= 4:
            assert bar.maximum() == 0 and rows[-1].bottom() == height - 1
    view.deleteLater()


def test_split_icon():
    assert split_icon("✓ Успешно") == ("✓", "Успешно")
    assert split_icon("⚠ Пропущено") == ("⚠", "Пропущено")
    assert split_icon("Ручное копирование: A") == ("", "Ручное копирование: A")


def test_history_panel_shows_entries_newest_last(themed):
    panel = HistoryPanel()
    assert panel.visible_entries() == [] and not panel.empty_box.isHidden() and panel.view.isHidden()
    entries = [HistoryEntry(datetime(2026, 10, 5, 9, 0), "Плановое копирование: A", (), ("a",)),
               HistoryEntry(datetime(2026, 10, 5, 9, 2), "✓ Успешно скопировано 3 файла", ("x",), ("a",))]
    panel.set_entries(entries)
    assert panel.plain_text().splitlines() == ["05.10.2026 09:00  Плановое копирование: A",
                                               "05.10.2026 09:02  ✓ Успешно скопировано 3 файла",
                                               " " * 20 + "x"]
    assert panel.view.height() <= 150
    panel.deleteLater()


def test_history_rows_draw_their_own_entry_after_trim(themed, monkeypatch):
    # кэш раскладок не должен отдавать строке текст удаленной записи (раньше ключом был id(entry))
    from backup_app.frontend import history_panel
    monkeypatch.setattr(history_panel, "HISTORY_VIEW_LIMIT", 5)
    panel = HistoryPanel()
    panel.resize(900, 300)
    for i in range(120):
        details = tuple(f"деталь {k}" for k in range(i % 3))
        panel.add_entry(HistoryEntry(datetime(2026, 10, 5, 9, 0), f"✓ запись {i} " + "текст " * (i % 7), details))
        entry = panel.view.model_.entries[-1]
        _icon, head, _h, parts, _height = panel.view.delegate._parts(entry, 900)
        assert head.text() == entry.text[2:] and len(parts) == len(entry.details)
    panel.deleteLater()


def test_history_rows_follow_width_after_resize(themed):
    from PyQt5.QtTest import QTest
    from backup_app.frontend import history_panel
    panel = HistoryPanel()
    long_text = "✓ " + "очень длинная запись истории " * 8
    panel.set_entries([HistoryEntry(datetime(2026, 10, 5, 9, 0), "Короткая"),
                       HistoryEntry(datetime(2026, 10, 5, 9, 1), long_text)])
    panel.resize(1400, 300)
    panel.show()
    QTest.qWait(history_panel.RELAYOUT_MS + 80)
    view = panel.view
    one_line = view.visualRect(view.model_.index(1, 0)).height()
    panel.resize(500, 300)
    QTest.qWait(history_panel.RELAYOUT_MS + 80)
    rect = view.visualRect(view.model_.index(1, 0))
    assert rect.height() > one_line            # длинная запись перенеслась
    assert rect.width() == view.viewport().width()
    assert view.visualRect(view.model_.index(0, 0)).height() == view.delegate.row_height(
        view.model_.entries[0], rect.width())
    panel.deleteLater()


# --------------------------------------------------------------------------- раскладка с переносом
def _row(widths):
    host = QWidget()
    row = W.FlexRow(host, hgap=8, vgap=8)
    buttons = []
    for w in widths:
        b = QWidget()
        b.setFixedSize(w, 28)
        buttons.append(b)
    return host, row, buttons


def test_flex_row_wraps_and_grows(themed):
    host, row, (a, b, c) = _row((100, 100, 100))
    row.add(a, basis=100, grow=1)
    row.add_spacer()
    row.add(b)
    row.add(c)
    host.resize(500, 100)
    row.setGeometry(host.rect())
    assert row.heightForWidth(500) == 28
    assert c.geometry().right() == 499 and b.geometry().right() == 391
    assert row.heightForWidth(250) == 28 * 2 + 8
    host.resize(250, 100)
    row.setGeometry(host.rect())
    assert c.geometry().y() == 36 and c.geometry().x() == 0
    host.deleteLater()


def test_flex_row_shrinks_to_min_width(themed):
    host = QWidget()
    row = W.FlexRow(host, hgap=10)
    label = W.ElidedLabel("Очень длинная подпись, которая не помещается в строку")
    button = QPushButton("Кнопка")
    row.add(label, basis=0, grow=1, min_width=0)   # flex: 1 1 0; min-width: 0
    row.add(button)
    host.resize(200, 50)
    row.setGeometry(host.rect())
    assert button.geometry().right() == 199 and button.geometry().y() <= label.geometry().bottom()
    assert label.width() == 200 - 10 - button.width() and label.is_elided()
    other_host = QWidget()
    other = W.FlexRow(other_host, hgap=10)
    wide = W.ElidedLabel("Очень длинная подпись, которая не помещается в строку")
    other.add(wide, min_width=0)   # flex-basis: auto — не помещается и занимает строку целиком
    other.add(QPushButton("Кнопка"))
    assert other.heightForWidth(200) > 40
    other_host.deleteLater()
    host.deleteLater()


def test_exact_font_width(themed):
    from PyQt5.QtGui import QFontMetricsF
    exact = theme.font_exact("regular", 12.5)
    low = QFontMetricsF(theme.font("regular", 12)).horizontalAdvance("Следующее копирование")
    high = QFontMetricsF(theme.font("regular", 13)).horizontalAdvance("Следующее копирование")
    width = QFontMetricsF(exact).horizontalAdvance("Следующее копирование")
    assert low < width < high
    assert theme.font_exact("regular", 13).pointSizeF() == theme.font("regular", 13).pointSizeF()
    assert os.path.isdir(theme.fonts_dir())
