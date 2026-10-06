"""Согласование слов с числами в сообщениях."""
import pytest

from backup_app.backend.wording import count_files, count_tabs_genitive


@pytest.mark.parametrize("count, text", [
    (0, "0 файлов"), (1, "1 файл"), (2, "2 файла"), (4, "4 файла"), (5, "5 файлов"), (11, "11 файлов"),
    (14, "14 файлов"), (21, "21 файл"), (22, "22 файла"), (111, "111 файлов"), (152, "152 файла"),
])
def test_count_files(count, text):
    assert count_files(count) == text


def test_count_tabs_genitive():
    assert [count_tabs_genitive(count) for count in (2, 5, 21)] == ["2 вкладок", "5 вкладок", "21 вкладки"]
