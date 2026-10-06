"""Пути к иконкам с учётом сборки PyInstaller."""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return PROJECT_ROOT


def resource_path(*parts: str) -> str:
    return os.path.join(resource_root(), *parts)
