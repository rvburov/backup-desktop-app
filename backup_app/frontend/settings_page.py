"""Страница «Настройки»: общие настройки приложения (автозапуск, фон, уведомления, пропущенное
копирование, лимит размера файла) и сброс. Расписание и параметры копирования — в каждой вкладке."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QSpinBox, QVBoxLayout, QWidget

from ..backend import MAX_PATH_LENGTH, SECURITY_TAG, AppConfig
from . import widgets as W
from .constants import SECURITY_HINT
from .theme import C

PAGE_SUBTITLE = ("Общие для всех вкладок и сохраняются автоматически. Расписание и параметры копирования "
                 "задаются в каждой вкладке.")
SWITCHES = (
    ("auto_start", "Автозапуск при входе в систему",
     "Приложение запускается свернутым в трей. Запущенные расписания возобновляются при каждом запуске программы."),
    ("minimize_to_tray", "Фоновый режим работы",
     "Закрытие и сворачивание окна прячут приложение в трей, копирование по расписанию продолжается."),
    ("show_notifications", "Уведомления о начале и результате копирования",
     "Всплывающие уведомления у значка в трее."),
    ("run_missed", "Выполнять пропущенное копирование при следующем запуске",
     "Если компьютер был выключен в назначенное время, копирование начнется через несколько секунд после запуска."),
)
MAX_SIZE_LABEL = "Максимальный размер файла, ГБ (0 — без ограничения):"
MAX_SIZE_LIMIT = 100_000
RESET_HINT = ("Эта функция очистит все настройки и восстановит значения по умолчанию. Полезно при возникновении "
              "проблем в работе приложения.")
RESET_BUTTON = "Сбросить все настройки по умолчанию"


class SettingsPage(QWidget):
    """Сигналы: changed — изменилась общая настройка (кроме автозапуска), autostart_toggled(bool),
    reset_requested — пользователь нажал «Сбросить»."""

    changed = pyqtSignal()
    autostart_toggled = pyqtSignal(bool)
    reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self.setProperty("kind", "page")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(W.label("Настройки", "h1"))
        head.addWidget(W.WrapAnywhereLabel(PAGE_SUBTITLE, "secondary-muted"))
        root.addLayout(head)

        # Запуск и работа в фоне
        card = QFrame()
        card.setProperty("kind", "card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        header = QWidget()
        h_lay = W.FlexRow(header, hgap=8, vgap=8)
        h_lay.setContentsMargins(14, 9, 14, 9)
        h_lay.add(W.IconLabel("monitor", C.TEXT2, 16))
        h_lay.add(W.label("Запуск и работа в фоне", "h2"))
        h_lay.add_spacer()
        lay.addWidget(header)
        lay.addWidget(W.hline())
        self.rows = {}
        for key, title, hint in SWITCHES:
            row = W.SwitchRow(title, hint, top_border=True, margins=(14, 10, 14, 10))
            if key == "auto_start":
                row.toggled.connect(self._on_autostart)
            else:
                row.toggled.connect(self._on_changed)
            lay.addWidget(row)
            self.rows[key] = row
        root.addWidget(card)

        # Безопасность
        card = QFrame()
        card.setProperty("kind", "card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        header = QWidget()
        h_lay = W.FlexRow(header, hgap=8, vgap=8)
        h_lay.add(W.IconLabel("shield-plain", C.TEXT2, 16))
        h_lay.add(W.label("Безопасность", "h2"))
        h_lay.add_spacer()
        lay.addWidget(header)
        size_row = QWidget()
        s_lay = W.FlexRow(size_row, hgap=12, vgap=8)
        s_lay.add(W.WrapAnywhereLabel(MAX_SIZE_LABEL, "medium"), min_width=0)
        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(0, MAX_SIZE_LIMIT)
        self.max_size_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.max_size_spin.setFixedWidth(96)
        self.max_size_spin.setAccessibleName(MAX_SIZE_LABEL)
        self.max_size_spin.valueChanged.connect(self._on_changed)
        s_lay.add(self.max_size_spin)
        s_lay.add_spacer()
        lay.addWidget(size_row)
        lay.addWidget(W.WrapAnywhereLabel(SECURITY_HINT.format(max_path=MAX_PATH_LENGTH, tag=SECURITY_TAG), "note-sm"))
        root.addWidget(card)

        # Сброс
        card = QFrame()
        card.setProperty("kind", "card")
        row_lay = W.FlexRow(card, hgap=12, vgap=12)
        row_lay.setContentsMargins(14, 12, 14, 12)
        text = QWidget()
        t_lay = QVBoxLayout(text)
        t_lay.setContentsMargins(0, 0, 0, 0)
        t_lay.setSpacing(0)
        t_lay.addWidget(W.label("Сброс настроек", "h2"))
        t_lay.addWidget(W.WrapAnywhereLabel(RESET_HINT, "muted"))
        row_lay.add(text, basis=280, grow=1, min_width=0)
        self.reset_button = W.Button(RESET_BUTTON, "danger")
        self.reset_button.clicked.connect(self.reset_requested)
        row_lay.add(self.reset_button)
        root.addWidget(card)
        root.addStretch(1)

    # ------------------------------------------------------------ данные
    def apply_config(self, config: AppConfig) -> None:
        self._loading = True
        try:
            for key, row in self.rows.items():
                row.set_checked(bool(getattr(config, key)))
            self.max_size_spin.setValue(max(0, min(MAX_SIZE_LIMIT, int(config.max_file_size_gb))))
        finally:
            self._loading = False

    def value(self, key: str) -> bool:
        return self.rows[key].is_checked()

    def set_checked(self, key: str, on: bool) -> None:
        """Переключить как пользователь (с сигналом)."""
        self.rows[key].set_checked(on, silent=False)

    def set_autostart_silent(self, on: bool) -> None:
        self.rows["auto_start"].set_checked(on)

    def max_file_size(self) -> int:
        return self.max_size_spin.value()

    def set_busy(self, busy: bool) -> None:
        self.reset_button.setEnabled(not busy)

    def _on_changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def _on_autostart(self, on: bool) -> None:
        if not self._loading:
            self.autostart_toggled.emit(on)
