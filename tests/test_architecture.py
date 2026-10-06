"""Границы между бэкендом и фронтендом проверяются автоматически."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT, "backup_app", "backend")
FRONTEND_DIR = os.path.join(ROOT, "backup_app", "frontend")


def sources(directory):
    for name in sorted(os.listdir(directory)):
        if name.endswith(".py"):
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as handle:
                yield name, handle.read()


def test_backend_imports_without_qt_and_frontend():
    modules = ["backup_app", "backup_app.backend"] + [
        f"backup_app.backend.{name[:-3]}" for name, _ in sources(BACKEND_DIR) if name != "__init__.py"]
    code = (
        "import importlib, sys\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        "bad = sorted(m for m in sys.modules if m.startswith(('PyQt5', 'backup_app.frontend')))\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_backend_sources_do_not_import_qt_or_frontend():
    forbidden = re.compile(r"^\s*(from|import)\s+(PyQt5|\.\.frontend|backup_app\.frontend|\.\.\s+import\s+frontend)",
                           re.MULTILINE)
    for name, text in sources(BACKEND_DIR):
        assert not forbidden.search(text), name


def test_frontend_uses_only_the_backend_package_api():
    for name, text in sources(FRONTEND_DIR):
        assert not re.search(r"from \.\.backend\.\w+ import", text), name
        assert not re.search(r"import backup_app\.backend\.", text), name


def test_frontend_has_no_file_copying_or_threads():
    forbidden = ("import shutil", "os.walk", "os.scandir", "import threading", "os.path.exists(item")
    for name, text in sources(FRONTEND_DIR):
        for pattern in forbidden:
            assert pattern not in text, f"{name}: {pattern}"
