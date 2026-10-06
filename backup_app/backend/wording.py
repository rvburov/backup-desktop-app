"""Согласование слов с числами в сообщениях: 1 файл, 2 файла, 5 файлов."""


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа: one для 1 и 21, few для 2–4 и 22–24, many для остальных."""
    count = abs(count) % 100
    if 11 <= count <= 14:
        return many
    last = count % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def count_files(count: int) -> str:
    """«1 файл», «3 файла», «12 файлов»."""
    return f"{count} {plural(count, 'файл', 'файла', 'файлов')}"


def count_tabs_genitive(count: int) -> str:
    """Для оборота «из N вкладок»: «из 2 вкладок», «из 21 вкладки»."""
    return f"{count} {plural(count, 'вкладки', 'вкладок', 'вкладок')}"
