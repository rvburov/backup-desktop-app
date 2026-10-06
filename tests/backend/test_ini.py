"""Совместимость модуля ini с форматом QSettings."""
import os

import pytest

from backup_app.backend import ini

BS = chr(92)


def esc(*parts):
    """Склеивает строку, где каждый элемент кроме первого начинается с обратной косой черты."""
    return parts[0] + "".join(BS + part for part in parts[1:])


# Текст, который записал QSettings (PyQt5 5.15, IniFormat, UTF-8) для набора значений.
QT_TEXT = (
    "[General]\r\n"
    "empty=@Invalid()\r\n"
    + 'one="@Variant(' + esc("", "0", "0", "0", "t", "0", "0", "0", "x1", "0", "0", "0", "n", "0", "0", "0",
                             "x1a", "0", "x43", "0:", "0/", "x4", "x1f", "x4", "x30", "x4?", "x4:", "x4",
                             "x30", "0 ", "x4>", "x4", "x34", "x4", "x38", 'x4=)"') + "\r\n"
    + 'two=C:/a, "C:/b, с запятой"\r\n'
    + "win=C:" + BS + BS + "Users" + BS + BS + "x\r\n"
    + "at=@@home\r\n"
    + "flag=true\r\n"
    + "num=5\r\n"
    + 'spaces=" lead"\r\n'
    + "quote=a" + BS + '"b\r\n'
    + "ctrl=a" + BS + "tb" + BS + "nc\r\n"
    + "\r\n[Tab_0]\r\n"
    + "source_folders=@Variant(" + esc("", "0", "0", "0", "t", "0", "0", "0", "x1", "0", "0", "0", "n", "0",
                                       "0", "0", "b", "0", "x44", "0:", "0/", "0x)") + "\r\n"
    + "tab_title=Без названия\r\n"
    + "\r\n[%General]\r\nodd=x\r\n"
)

QT_VALUES = {
    "empty": None,
    "one": ["C:/Папка один"],
    "two": ["C:/a", "C:/b, с запятой"],
    "win": "C:" + BS + "Users" + BS + "x",
    "at": "@home",
    "flag": "true",
    "num": "5",
    "spaces": " lead",
    "quote": 'a"b',
    "ctrl": "a\tb\nc",
    "Tab_0/source_folders": ["D:/x"],
    "Tab_0/tab_title": "Без названия",
    "General/odd": "x",
}

TRICKY = [
    "plain", "", " lead", "trail ", "a,b", "a;b", "a=b", 'quo"te', BS + "back" + BS + "slash",
    "@at", "@@double", "@Invalid()", "tab\tnew\nline\rret", "nul\0end", "\x01\x1fctl", "Кириллица",
    "emoji 😀", "C:" + BS + "Users" + BS + "Папка, с запятой", "x" * 300,
]


def test_reads_text_written_by_qsettings():
    assert ini.parse_ini(QT_TEXT) == QT_VALUES


@pytest.mark.parametrize("value", TRICKY)
def test_single_value_roundtrip(value):
    text = ini.format_ini([("", [("key", value)])])
    assert ini.parse_ini(text)["key"] == value


def test_list_roundtrip():
    values = [item for item in TRICKY if item]
    text = ini.format_ini([("", [("key", values)])])
    assert ini.parse_ini(text)["key"] == values


def test_empty_list_and_none():
    text = ini.format_ini([("", [("a", []), ("b", None)])])
    assert "a=@Invalid()" in text and "b=@Invalid()" in text
    assert ini.parse_ini(text) == {"a": None, "b": None}


def test_bool_and_int_values():
    text = ini.format_ini([("", [("flag", True), ("off", False), ("num", 42)])])
    assert ini.parse_ini(text) == {"flag": "true", "off": "false", "num": "42"}


def test_sections_and_special_general_group():
    text = ini.format_ini([("", [("top", "1")]), ("Tab_0", [("x", "2")]), ("General", [("y", "3")])])
    assert "[General]" in text and "[Tab_0]" in text and "[%General]" in text
    assert ini.parse_ini(text) == {"top": "1", "Tab_0/x": "2", "General/y": "3"}


def test_key_escaping_roundtrip():
    text = ini.format_ini([("", [("ключ с пробелом/и слешем", "v")])])
    assert ini.parse_ini(text) == {"ключ с пробелом/и слешем": "v"}


def test_comments_bom_and_line_endings():
    text = "\ufeff; комментарий\n[General]\r\nkey=value ; хвост\nother = spaced value  \n\n;[Tab_0]\n"
    assert ini.parse_ini(text) == {"key": "value", "other": "spaced value"}


def test_quoted_value_keeps_semicolon_and_spaces():
    assert ini.parse_ini('[General]\nkey=" a;b "\n') == {"key": " a;b "}


def test_broken_variant_is_ignored():
    assert ini.parse_ini("[General]\nkey=@Variant(" + BS + "0" + BS + "0)\n") == {"key": None}


def test_write_is_atomic(tmp_path):
    path = str(tmp_path / "settings.ini")
    ini.write_ini(path, [("", [("a", "1")])])
    ini.write_ini(path, [("", [("a", "2")])])
    assert ini.read_ini(path) == {"a": "2"}
    assert os.listdir(tmp_path) == ["settings.ini"]


def test_read_missing_file(tmp_path):
    assert ini.read_ini(str(tmp_path / "nope.ini")) == {}


def test_cross_check_with_qsettings(tmp_path, request):
    """Файл, записанный QSettings, читается нами, а записанный нами читается QSettings."""
    qt_core = pytest.importorskip("PyQt5.QtCore")
    # общий QApplication прогона, а не свой QCoreApplication: удаление своего выключило бы в PyQt5
    # слежение за удалением объектов Qt до конца прогона (см. qapp в conftest.py)
    assert request.getfixturevalue("qapp") is qt_core.QCoreApplication.instance()
    # Символы вне BMP Qt 5 сам записывает с ошибкой, поэтому в сверке их нет.
    items = [item for item in TRICKY if item and "\0" not in item and max(map(ord, item)) <= 0xFFFF]
    values = {"items": items, "one": ["C:/Папка"], "text": "C:" + BS + "x, y", "at": "@x"}

    qt_path = str(tmp_path / "qt.ini")
    settings = qt_core.QSettings(qt_path, qt_core.QSettings.IniFormat)
    settings.setIniCodec("UTF-8")
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()
    assert ini.read_ini(qt_path) == values

    our_path = str(tmp_path / "ours.ini")
    ini.write_ini(our_path, [("", list(values.items()))])
    settings = qt_core.QSettings(our_path, qt_core.QSettings.IniFormat)
    settings.setIniCodec("UTF-8")
    read_back = {key: settings.value(key) for key in values}
    assert read_back["items"] == values["items"]
    assert read_back["one"] == "C:/Папка"  # один элемент пишется строкой, как ждут старые версии
    assert read_back["text"] == values["text"] and read_back["at"] == "@x"
