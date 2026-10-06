#!/usr/bin/env python3
"""Точка входа приложения резервного копирования.

Запуск:  python backup-app.py            — открыть окно
         python backup-app.py --minimized — запустить в фоне (иконка в трее)

Код приложения находится в пакете backup_app/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backup_app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
