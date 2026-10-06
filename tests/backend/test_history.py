"""История копирования: формат записей, файл истории и срок хранения."""
from datetime import datetime, timedelta

from backup_app.backend import history as history_module
from backup_app.backend.history import (DETAIL_INDENT, MAX_DETAILS, HistoryEntry, HistoryStore, limit_details,
                                        parse_history)

NOW = datetime(2026, 10, 6, 12, 0)


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


def entry(days_ago, text, details=()):
    return HistoryEntry(NOW - timedelta(days=days_ago), text, tuple(details))


def write_entries(path, *entries, encoding="utf-8"):
    path.write_text("\n".join(line for item in entries for line in item.lines()) + "\n", encoding=encoding)


def test_entry_lines_show_time_text_and_indented_details():
    item = HistoryEntry(datetime(2026, 10, 8, 9, 1), "⚠ Скопировано 2 файла, ошибок: 1",
                        ("Не скопирован C:/Документы/отчет.docx: файл занят другой программой",))
    assert item.lines() == [
        "08.10.2026 09:01  ⚠ Скопировано 2 файла, ошибок: 1",
        DETAIL_INDENT + "Не скопирован C:/Документы/отчет.docx: файл занят другой программой",
    ]


def test_parse_restores_entries_and_skips_garbage():
    items = [entry(2, "Ручное копирование: Документы"),
             entry(1, "⚠ Скопировано 2 файла, ошибок: 1", ["первая ошибка", "вторая ошибка"])]
    garbage = ("строка без даты\n"
               "    подробность без записи\n"
               "99.99.2026 10:00  запись с неверной датой\n"
               "    подробность неверной записи\n")
    text = garbage + "\n".join(line for item in items for line in item.lines()) + "\n\n"
    assert parse_history(text) == items


def test_limit_details_keeps_first_ones_and_counts_the_rest():
    details = [f"ошибка {number}" for number in range(MAX_DETAILS + 5)]
    limited = limit_details(details)
    assert limited[:MAX_DETAILS] == tuple(details[:MAX_DETAILS])
    assert limited[MAX_DETAILS:] == ("…и еще 5, см. подробный журнал",)
    assert limit_details(["одна", ""]) == ("одна",)


def test_store_appends_and_survives_restart(tmp_path):
    path = str(tmp_path / "history.txt")
    store = HistoryStore(path, now=Clock(NOW))
    first = entry(1, "Ручное копирование: Данные")
    second = entry(0, "⚠ Скопировано 1 файл, ошибок: 1", ["Не скопирован a.txt: нет доступа"])
    store.add(first)
    store.add(second)
    assert store.entries() == [first, second]
    assert HistoryStore(path, now=Clock(NOW)).entries() == [first, second]


def test_entries_older_than_a_year_are_removed(tmp_path):
    path = tmp_path / "history.txt"
    old, recent = entry(400, "✓ Старое копирование"), entry(10, "✓ Недавнее копирование")
    write_entries(path, old, recent)
    assert HistoryStore(str(path), now=Clock(NOW)).entries() == [recent]
    assert "Старое" not in path.read_text(encoding="utf-8")


def test_entries_expire_while_the_app_keeps_running(tmp_path):
    path = str(tmp_path / "history.txt")
    clock = Clock(NOW)
    store = HistoryStore(path, now=clock)
    store.add(entry(0, "✓ Первое копирование"))
    clock.moment = NOW + timedelta(days=366)
    later = HistoryEntry(clock.moment, "✓ Второе копирование")
    store.add(later)
    assert store.entries() == [later]
    assert HistoryStore(path, now=clock).entries() == [later]


def test_file_saved_with_bom_is_read(tmp_path):
    path = tmp_path / "history.txt"
    item = entry(1, "✓ Файл сохранен в Блокноте")
    write_entries(path, item, encoding="utf-8-sig")
    assert HistoryStore(str(path), now=Clock(NOW)).entries() == [item]


def test_unreadable_file_is_only_appended(tmp_path, monkeypatch):
    path = tmp_path / "history.txt"
    write_entries(path, entry(400, "✓ Старое копирование"))

    def broken_read(_path):
        raise PermissionError(13, "Отказано в доступе")

    monkeypatch.setattr(history_module, "_read_text", broken_read)
    clock = Clock(NOW)
    store = HistoryStore(str(path), now=clock)
    assert store.entries() == []
    store.add(entry(0, "✓ Новое копирование"))
    clock.moment = NOW + timedelta(days=400)
    store.add(HistoryEntry(clock.moment, "✓ Еще одно копирование"))
    text = path.read_text(encoding="utf-8")
    assert "Старое копирование" in text and "Новое копирование" in text and "Еще одно копирование" in text
