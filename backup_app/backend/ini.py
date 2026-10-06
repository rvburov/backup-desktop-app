"""Чтение и запись INI-файлов в формате QSettings без зависимости от Qt.

Прежние версии приложения писали настройки через QSettings (IniFormat, UTF-8).
Модуль читает и пишет тот же формат: старые файлы открываются без изменений,
а новые файлы по-прежнему читаются старыми версиями.

Правила формата:
- секция [General] хранит ключи верхнего уровня, другие секции хранят группы ключей;
- список строк записывается через «, », пустой список записывается как @Invalid();
- строка с символами «,;=» или пробелами по краям берётся в кавычки;
- обратная косая черта, кавычки и управляющие символы экранируются;
- строка, которая начинается с @, записывается с двумя @;
- список из одного элемента PyQt5 сохранял как @Variant(...), такой формат тоже читается.
"""
import os
import struct
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

IniValue = Union[None, bool, int, str, List[Optional[str]]]
Section = Tuple[str, Sequence[Tuple[str, IniValue]]]

_SPACE = " \t\r\n"
_SPECIAL = "\r\n\";=\\"
_HEX_DIGITS = "0123456789abcdefABCDEF"
_KEY_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
_READ_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
                 '"': '"', "?": "?", "'": "'", "\\": "\\"}
_WRITE_ESCAPES = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}

# Типы QVariant в потоке QDataStream (версия Qt 4.0), которые встречаются в настройках.
_QT_INVALID, _QT_BOOL, _QT_INT, _QT_UINT, _QT_LONGLONG, _QT_ULONGLONG, _QT_DOUBLE = 0, 1, 2, 3, 4, 5, 6
_QT_LIST, _QT_STRING, _QT_STRINGLIST = 9, 10, 11


# ---------------------------------------------------------------- чтение
def read_ini(path: str) -> Dict[str, IniValue]:
    """Значения из файла: {"ключ": значение, "Группа/ключ": значение}. Нет файла — пустой словарь."""
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as handle:
        data = handle.read()
    return parse_ini(data.decode("utf-8", errors="replace"))


def parse_ini(text: str) -> Dict[str, IniValue]:
    if text.startswith("﻿"):
        text = text[1:]
    values: Dict[str, IniValue] = {}
    section = ""
    for line, equals in _logical_lines(text):
        if line.startswith("["):
            close = line.find("]")
            name = (line[1:close] if close != -1 else line[1:]).strip()
            if name.lower() == "general":
                section = ""
            elif name.lower() == "%general":
                section = name[1:] + "/"
            else:
                section = _unescape_key(name) + "/"
            continue
        if equals < 0:
            continue
        key_end = equals
        while key_end > 0 and line[key_end - 1] in " \t":
            key_end -= 1
        key = section + _unescape_key(line[:key_end])
        values[key] = _decode_value(line[equals + 1:])
    return values


def _logical_lines(data: str) -> Iterator[Tuple[str, int]]:
    """Строки INI с позицией «=»: пропускает комментарии «;», учитывает кавычки и перенос через «\\»."""
    n = len(data)
    pos = 0
    while True:
        line_start = pos
        while line_start < n and data[line_start] in _SPACE:
            line_start += 1
        i = line_start
        in_quotes = False
        equals = -1
        while i < n:
            ch = data[i]
            i += 1
            if ch not in _SPECIAL:
                continue
            if ch == "=":
                if not in_quotes and equals == -1:
                    equals = i - 1
            elif ch in "\r\n":
                if i == line_start + 1:
                    line_start += 1
                elif not in_quotes:
                    i -= 1
                    break
            elif ch == "\\":
                if i < n:
                    following = data[i]
                    i += 1
                    if i < n and {following, data[i]} == {"\r", "\n"}:
                        i += 1
            elif ch == '"':
                in_quotes = not in_quotes
            else:  # ";"
                if i == line_start + 1:
                    while i < n and data[i] not in "\r\n":
                        i += 1
                    while i < n and data[i] in _SPACE:
                        i += 1
                    line_start = i
                elif not in_quotes:
                    i -= 1
                    break
        pos = i
        if i <= line_start:
            return
        yield data[line_start:i], (equals - line_start if equals >= 0 else -1)


def _unescape_key(raw: str) -> str:
    result = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\":
            result.append("/")
            i += 1
            continue
        if ch != "%" or i == n - 1:
            result.append(ch)
            i += 1
            continue
        first, digits = i + 1, 2
        if raw[i + 1] == "U":
            first, digits = i + 2, 4
        chunk = raw[first:first + digits]
        if len(chunk) < digits or any(c not in _HEX_DIGITS for c in chunk):
            result.append("%")
            i += 1
            continue
        result.append(chr(int(chunk, 16)))
        i = first + digits
    return "".join(result)


def _unescape_value(raw: str) -> Tuple[str, Optional[List[str]]]:
    """Разбирает значение: строку или список через запятую с кавычками и экранированием."""
    n = len(raw)
    current: List[str] = []
    items: Optional[List[str]] = None
    in_quotes = False
    quoted = False
    stopped_on_escape = False

    def skip_spaces(position: int) -> int:
        while position < n and raw[position] in " \t":
            position += 1
        return position

    def chop(limit: int) -> None:
        while len(current) > limit and current[-1] in (" ", "\t"):
            current.pop()

    i = skip_spaces(0)
    chop_limit = 0
    while i < n:
        ch = raw[i]
        if ch == "\\":
            i += 1
            if i >= n:
                stopped_on_escape = True
                break
            ch = raw[i]
            i += 1
            if ch in _READ_ESCAPES:
                current.append(_READ_ESCAPES[ch])
            elif ch == "x":
                if i >= n:
                    stopped_on_escape = True
                    break
                if raw[i] in _HEX_DIGITS:
                    value = 0
                    while i < n and raw[i] in _HEX_DIGITS:
                        value = value * 16 + int(raw[i], 16)
                        i += 1
                    current.append(chr(value & 0xFFFF))
                    if i >= n:
                        stopped_on_escape = True
                        break
            elif "0" <= ch <= "7":
                value = int(ch)
                while i < n and "0" <= raw[i] <= "7":
                    value = value * 8 + int(raw[i])
                    i += 1
                current.append(chr(value & 0xFFFF))
                if i >= n:
                    stopped_on_escape = True
                    break
            elif ch in "\r\n":
                if i < n and raw[i] in "\r\n" and raw[i] != ch:
                    i += 1
            chop_limit = len(current)
            continue
        if ch == '"':
            i += 1
            quoted = True
            in_quotes = not in_quotes
            if not in_quotes:
                i = skip_spaces(i)
                chop_limit = len(current)
            continue
        if ch == "," and not in_quotes:
            if not quoted:
                chop(chop_limit)
            if items is None:
                items = []
            items.append("".join(current))
            current = []
            quoted = False
            i = skip_spaces(i + 1)
            chop_limit = 0
            continue
        end = i + 1
        while end < n and raw[end] not in '\\",':
            end += 1
        current.extend(raw[i:end])
        i = end
    if not stopped_on_escape and not quoted:
        chop(chop_limit)
    text = "".join(current)
    if items is not None:
        items.append(text)
    return text, items


def _decode_value(raw: str) -> IniValue:
    text, items = _unescape_value(raw)
    if items is not None:
        return [_string_to_value(item) for item in items]
    return _string_to_value(text)


def _string_to_value(text: str):
    if text.startswith("@"):
        if text.endswith(")"):
            if text.startswith("@Variant("):
                try:
                    return _decode_variant(text[9:-1])
                except (ValueError, IndexError, struct.error, UnicodeError):
                    return None
            if text.startswith("@String("):
                return text[8:-1]
            if text.startswith("@ByteArray("):
                return text[11:-1]
            if text == "@Invalid()" or text.startswith(("@DateTime(", "@Rect(", "@Size(", "@Point(")):
                return None
        if text.startswith("@@"):
            return text[1:]
    return text


def _decode_variant(payload: str):
    data = payload.encode("latin-1")
    value, _ = _read_variant(data, 0)
    return value


def _read_u32(data: bytes, pos: int) -> Tuple[int, int]:
    return struct.unpack_from(">I", data, pos)[0], pos + 4


def _read_qstring(data: bytes, pos: int) -> Tuple[str, int]:
    length, pos = _read_u32(data, pos)
    if length == 0xFFFFFFFF:
        return "", pos
    raw = data[pos:pos + length]
    if len(raw) != length:
        raise ValueError("Обрезанная строка в @Variant")
    return raw.decode("utf-16-be"), pos + length


def _read_variant(data: bytes, pos: int):
    type_id, pos = _read_u32(data, pos)
    if type_id == _QT_INVALID:
        return None, pos
    if type_id == _QT_BOOL:
        return bool(data[pos]), pos + 1
    if type_id in (_QT_INT, _QT_UINT):
        return struct.unpack_from(">i" if type_id == _QT_INT else ">I", data, pos)[0], pos + 4
    if type_id in (_QT_LONGLONG, _QT_ULONGLONG):
        return struct.unpack_from(">q" if type_id == _QT_LONGLONG else ">Q", data, pos)[0], pos + 8
    if type_id == _QT_DOUBLE:
        return struct.unpack_from(">d", data, pos)[0], pos + 8
    if type_id == _QT_STRING:
        return _read_qstring(data, pos)
    if type_id in (_QT_LIST, _QT_STRINGLIST):
        count, pos = _read_u32(data, pos)
        items = []
        for _ in range(count):
            if type_id == _QT_LIST:
                item, pos = _read_variant(data, pos)
            else:
                item, pos = _read_qstring(data, pos)
            items.append(item)
        return items, pos
    raise ValueError(f"Неподдерживаемый тип в @Variant: {type_id}")


# ---------------------------------------------------------------- запись
def write_ini(path: str, sections: Sequence[Section]) -> None:
    """Записывает файл атомарно: сначала во временный файл, затем заменяет основной."""
    text = format_ini(sections)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def format_ini(sections: Sequence[Section], eol: Optional[str] = None) -> str:
    """Текст файла. Секция с пустым именем записывается как [General]."""
    eol = eol or ("\r\n" if os.name == "nt" else "\n")
    blocks = []
    for name, items in sections:
        if not name:
            header = "[General]"
        elif name.lower() == "general":
            header = "[%General]"
        else:
            header = f"[{_escape_key(name)}]"
        lines = [header] + [f"{_escape_key(key)}={format_value(value)}" for key, value in items]
        blocks.append(eol.join(lines) + eol)
    return eol.join(blocks)


def format_value(value: IniValue) -> str:
    if isinstance(value, (list, tuple)):
        if not value:
            return "@Invalid()"
        return ", ".join(_escape_string(_value_to_string(item)) for item in value)
    return _escape_string(_value_to_string(value))


def _value_to_string(value) -> str:
    if value is None:
        return "@Invalid()"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if "\0" in text:
        return f"@String({text})"
    if text.startswith("@"):
        return "@" + text
    return text


def _escape_string(text: str) -> str:
    if text == "@Invalid()":
        return text
    result = []
    needs_quotes = False
    escape_next_hex = False
    for ch in text:
        code = ord(ch)
        if ch in ";,=":
            needs_quotes = True
        if escape_next_hex and ch in _HEX_DIGITS:
            result.append(f"\\x{code:x}")
            continue
        escape_next_hex = False
        if ch == "\0":
            result.append("\\0")
            escape_next_hex = True
        elif ch in _WRITE_ESCAPES:
            result.append(_WRITE_ESCAPES[ch])
        elif ch in '"\\':
            result.append("\\" + ch)
        elif code <= 0x1F:
            result.append(f"\\x{code:x}")
            escape_next_hex = True
        else:
            result.append(ch)
    escaped = "".join(result)
    if needs_quotes or escaped.startswith(" ") or escaped.endswith(" "):
        escaped = f'"{escaped}"'
    return escaped


def _escape_key(key: str) -> str:
    result = []
    for ch in key:
        if ch == "/":
            result.append("\\")
        elif ch in _KEY_SAFE:
            result.append(ch)
        else:
            units = struct.unpack(f">{len(ch.encode('utf-16-be')) // 2}H", ch.encode("utf-16-be"))
            for unit in units:
                result.append(f"%{unit:02X}" if unit <= 0xFF else f"%U{unit:04X}")
    return "".join(result)
