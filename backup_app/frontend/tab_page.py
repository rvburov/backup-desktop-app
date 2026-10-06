"""Страница вкладки: списки папок и файлов для копирования и папка назначения.

Проверки путей выполняет бэкенд: страница получает объект validator с методами
source_problem, destination_problem и path_problem. Сама страница диск не читает.
"""
from typing import Iterable, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLineEdit, QListWidget,
                             QPushButton, QVBoxLayout, QWidget)

from ..backend import TabConfig

PROBLEM_PATH_COLOR = QColor("#c62828")


class TabPage(QWidget):
    changed = pyqtSignal()             # изменился состав вкладки
    title_changed = pyqtSignal(str)    # изменился заголовок
    problem = pyqtSignal(str, str)     # заголовок и текст предупреждения для пользователя

    def __init__(self, config: Optional[TabConfig] = None, validator=None, parent=None):
        super().__init__(parent)
        self.validator = validator
        layout = QVBoxLayout(self)

        self.title_edit = QLineEdit()
        self.title_edit.setStyleSheet("QLineEdit { font-weight: bold; border: none; background: transparent; }")
        self.title_edit.setAlignment(Qt.AlignCenter)
        self.title_edit.setToolTip("Название вкладки: нажмите, чтобы изменить")
        self.title_edit.editingFinished.connect(self._on_title_finished)
        layout.addWidget(self.title_edit)

        self.folders_list = QListWidget()
        layout.addWidget(self._build_group("Список папок", self.folders_list, [
            ("Добавить папку", self.add_folder),
            ("Удалить папку", self.remove_selected_folder),
            ("Очистить список", self.clear_folders),
        ]))

        self.files_list = QListWidget()
        layout.addWidget(self._build_group("Список файлов", self.files_list, [
            ("Добавить файл", self.add_files),
            ("Удалить файл", self.remove_selected_file),
            ("Очистить список", self.clear_files),
        ]))

        dest_group = QGroupBox("Папка сохранения")
        dest_layout = QHBoxLayout(dest_group)
        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        dest_layout.addWidget(self.dest_edit)
        dest_button = QPushButton("Выбрать папку")
        dest_button.clicked.connect(self.select_destination)
        dest_layout.addWidget(dest_button)
        layout.addWidget(dest_group)
        layout.addStretch()

        self.set_config(config or TabConfig())

    @staticmethod
    def _build_group(title: str, list_widget: QListWidget, buttons) -> QGroupBox:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(list_widget)
        row = QHBoxLayout()
        for text, handler in buttons:
            button = QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
        group_layout.addLayout(row)
        return group

    def _check(self, method: str, path: str) -> Optional[str]:
        if self.validator is None:
            return None
        return getattr(self.validator, method)(path)

    # ------------------------------------------------------------- данные
    @property
    def title(self) -> str:
        return self.title_edit.text().strip() or TabConfig().title

    @property
    def destination(self) -> str:
        return self.dest_edit.text().strip()

    def set_config(self, config: TabConfig) -> None:
        self.title_edit.setText(config.title or TabConfig().title)
        self._fill(self.folders_list, config.folders)
        self._fill(self.files_list, config.files)
        self.dest_edit.setText(config.destination or "")
        self.refresh_availability()

    def to_config(self) -> TabConfig:
        return TabConfig(
            title=self.title,
            folders=self._items(self.folders_list),
            files=self._items(self.files_list),
            destination=self.destination,
        )

    @staticmethod
    def _items(list_widget: QListWidget) -> List[str]:
        return [list_widget.item(index).text() for index in range(list_widget.count())]

    @staticmethod
    def _fill(list_widget: QListWidget, paths: Iterable[str]) -> None:
        list_widget.clear()
        for path in paths:
            if path:
                list_widget.addItem(path)

    def refresh_availability(self) -> None:
        """Подсвечивает пути, которые будут пропущены: недоступные или системные."""
        for list_widget in (self.folders_list, self.files_list):
            for index in range(list_widget.count()):
                item = list_widget.item(index)
                problem = self._check("path_problem", item.text())
                if problem:
                    item.setForeground(QBrush(PROBLEM_PATH_COLOR))
                    item.setToolTip(problem)
                else:
                    item.setData(Qt.ForegroundRole, None)
                    item.setToolTip("")

    # ----------------------------------------------------------- действия
    def _on_title_finished(self) -> None:
        title = self.title
        self.title_edit.setText(title)
        self.title_changed.emit(title)
        self.changed.emit()

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для копирования")
        if path:
            self.add_folder_path(path)

    def add_folder_path(self, path: str) -> bool:
        if not path or path in self._items(self.folders_list):
            return False
        problem = self._check("source_problem", path)
        if problem:
            self.problem.emit("Папка не добавлена", problem)
            return False
        self.folders_list.addItem(path)
        self.refresh_availability()
        self.changed.emit()
        return True

    def remove_selected_folder(self) -> None:
        row = self.folders_list.currentRow()
        if row >= 0:
            self.folders_list.takeItem(row)
            self.changed.emit()

    def clear_folders(self) -> None:
        self.folders_list.clear()
        self.changed.emit()

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для копирования")
        self.add_file_paths(files)

    def add_file_paths(self, paths: Iterable[str]) -> int:
        existing = set(self._items(self.files_list))
        added = 0
        refused = []
        for path in paths:
            if not path or path in existing:
                continue
            problem = self._check("source_problem", path)
            if problem:
                refused.append(problem)
                continue
            self.files_list.addItem(path)
            existing.add(path)
            added += 1
        if refused:
            self.problem.emit("Файлы не добавлены", "\n".join(refused))
        if added:
            self.refresh_availability()
            self.changed.emit()
        return added

    def remove_selected_file(self) -> None:
        row = self.files_list.currentRow()
        if row >= 0:
            self.files_list.takeItem(row)
            self.changed.emit()

    def clear_files(self) -> None:
        self.files_list.clear()
        self.changed.emit()

    def select_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для резервных копий")
        if path:
            self.set_destination(path)

    def set_destination(self, path: str) -> bool:
        problem = self._check("destination_problem", path)
        if problem:
            self.problem.emit("Папка не выбрана", problem)
            return False
        self.dest_edit.setText(path)
        self.changed.emit()
        return True
