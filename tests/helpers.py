"""Вспомогательные функции для тестов."""
import os
import time


def make_tree(root, spec):
    """Создаёт дерево файлов: {имя: содержимое | {вложенное дерево}}."""
    root = str(root)
    os.makedirs(root, exist_ok=True)
    for name, value in spec.items():
        path = os.path.join(root, name)
        if isinstance(value, dict):
            make_tree(path, value)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(value)


def list_rel(root):
    """Относительные пути всех файлов под root, отсортированные, с прямыми слешами."""
    root = str(root)
    result = []
    for current, _dirs, files in os.walk(root):
        for name in files:
            result.append(os.path.relpath(os.path.join(current, name), root).replace("\\", "/"))
    return sorted(result)


def pump(app, milliseconds):
    """Крутит цикл событий Qt заданное время."""
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def wait_for(app, condition, timeout=15.0):
    """Ждёт выполнения условия, обрабатывая события Qt."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return condition()
