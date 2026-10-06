"""Запуск пакета как модуля: python -m backup_app [--minimized]."""
import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
