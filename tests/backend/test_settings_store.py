import os
from datetime import datetime

from backup_app.backend.scheduler import PERIOD_DAILY, PERIOD_WEEKLY
from backup_app.backend.settings_store import AppConfig, SettingsStore, TabConfig

BS = chr(92)

LEGACY_INI = """[General]
period_type=Ежедневно
backup_time=09:00
weekday=0
monthday=1
keep_history=true
create_backup_folder=true
auto_start=false
timer_active=true
copy_folder_contents=false
copy_all_tabs=false
tab_count=2
tab_names=Мои документы, Фото

[Tab_0]
source_folders=C:/Users/User/Documents, C:/Users/User/Desktop
source_files=C:/Users/User/important.txt
destination_folder=D:/Backup
tab_title=Мои документы

[Tab_1]
source_folders=@Invalid()
source_files=@Invalid()
destination_folder=
tab_title=Фото
"""

# Так QSettings в прежних версиях сохранял вкладку, где выбрана ровно одна папка «D:/x».
QT_SINGLE_FOLDER_INI = (
    "[General]\r\ntab_count=1\r\n\r\n[Tab_0]\r\n"
    "source_folders=@Variant(" + BS + "0" + BS + "0" + BS + "0" + BS + "t" + BS + "0" + BS + "0" + BS + "0"
    + BS + "x1" + BS + "0" + BS + "0" + BS + "0" + BS + "n" + BS + "0" + BS + "0" + BS + "0" + BS + "b"
    + BS + "0" + BS + "x44" + BS + "0:" + BS + "0/" + BS + "0x)\r\n"
    "source_files=@Invalid()\r\n"
    "destination_folder=E:/Backup\r\n"
    "tab_title=Одна папка\r\n"
)


def store_at(tmp_path, name="settings.ini"):
    return SettingsStore(str(tmp_path / name))


def test_roundtrip_keeps_every_field(tmp_path):
    config = AppConfig(
        period_type=PERIOD_WEEKLY, backup_time="21:30", weekday=4, monthday=15,
        keep_history=False, copy_all_tabs=True, minimize_to_tray=False, run_missed=False,
        max_file_size_gb=10, active_tab=1,
        last_backup_time=datetime(2026, 10, 6, 12, 0, 5), timer_started_at=datetime(2026, 10, 1, 8, 0, 0),
        tabs=[
            TabConfig("Документы бухгалтерии", ["C:/Исходные данные", "D:/Фото 2026"],
                      ["C:/Исходные данные/ф.txt"], "D:/Копии"),
            TabConfig("Вторая", ["C:" + BS + "Папка, с запятой"], ["@файл"], "E:" + BS + "Копии"),
        ],
    )
    store_at(tmp_path).save(config)
    assert store_at(tmp_path).load() == config


def test_defaults_when_file_missing(tmp_path):
    assert store_at(tmp_path, "missing.ini").load() == AppConfig()


def test_legacy_ini_is_compatible(tmp_path):
    (tmp_path / "settings.ini").write_text(LEGACY_INI, encoding="utf-8")
    config = store_at(tmp_path).load()
    assert config.timer_active is True
    assert config.backup_time == "09:00" and config.period_type == PERIOD_DAILY
    assert [tab.title for tab in config.tabs] == ["Мои документы", "Фото"]
    assert config.tabs[0].folders == ["C:/Users/User/Documents", "C:/Users/User/Desktop"]
    assert config.tabs[0].files == ["C:/Users/User/important.txt"]
    assert config.tabs[0].destination == "D:/Backup"
    assert config.tabs[1].folders == [] and config.tabs[1].destination == ""
    # новые ключи получают значения по умолчанию
    assert config.minimize_to_tray and config.show_notifications and config.run_missed
    assert config.max_file_size_gb == 2 and config.active_tab == 0
    assert config.last_backup_time is None


def test_single_folder_saved_by_qsettings_is_read(tmp_path):
    """Список из одного пути старые версии сохраняли двоичным блоком @Variant."""
    (tmp_path / "settings.ini").write_bytes(QT_SINGLE_FOLDER_INI.encode("utf-8"))
    tab = store_at(tmp_path).load().tabs[0]
    assert tab == TabConfig("Одна папка", ["D:/x"], [], "E:/Backup")


def test_saved_file_is_readable_by_old_versions(tmp_path):
    """Один путь пишется обычной строкой: ее понимает и QSettings, и прежний код."""
    store_at(tmp_path).save(AppConfig(tabs=[TabConfig("A", ["C:/один"], [], "D:/x")]))
    text = (tmp_path / "settings.ini").read_text(encoding="utf-8")
    assert "source_folders=C:/один" in text
    assert "source_files=@Invalid()" in text
    assert "tab_names=A" in text


def test_shipped_example_ini_loads(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    example = os.path.join(root, "settings_ example.ini")
    content = open(example, encoding="utf-8").read()
    (tmp_path / "settings.ini").write_text(content, encoding="utf-8")
    config = store_at(tmp_path).load()
    assert config.backup_time == "09:00" and config.period_type == PERIOD_DAILY
    assert len(config.tabs) == 1 and config.max_file_size_gb == 2


def test_missing_paths_are_kept(tmp_path):
    """Отключенный диск не должен стирать пути из настроек."""
    config = AppConfig(tabs=[TabConfig("USB", ["X:/нет такого диска"], ["X:/нет.txt"], "Y:/нет")])
    store_at(tmp_path).save(config)
    assert store_at(tmp_path).load().tabs == config.tabs


def test_invalid_values_fall_back_to_defaults(tmp_path):
    (tmp_path / "settings.ini").write_text(
        "[General]\nperiod_type=Bogus\nbackup_time=99:99\nweekday=12\nmonthday=0\n"
        "tab_count=0\nlast_backup_time=yesterday\nkeep_history=maybe\nmax_file_size_gb=-5\n"
        "active_tab=7\n", encoding="utf-8")
    config = store_at(tmp_path).load()
    assert config.period_type == PERIOD_DAILY and config.backup_time == "00:00"
    assert config.weekday == 0 and config.monthday == 1
    assert len(config.tabs) == 1 and config.last_backup_time is None
    assert config.keep_history is True and config.max_file_size_gb == 2 and config.active_tab == 0


def test_reset_restores_defaults(tmp_path):
    store = store_at(tmp_path)
    store.save(AppConfig(copy_all_tabs=True, tabs=[TabConfig("A"), TabConfig("B")]))
    assert store.reset() == AppConfig()
    assert store_at(tmp_path).load() == AppConfig()


def test_save_removes_stale_tab_sections(tmp_path):
    store = store_at(tmp_path)
    store.save(AppConfig(tabs=[TabConfig("A"), TabConfig("B"), TabConfig("C")]))
    store.save(AppConfig(tabs=[TabConfig("Только одна")]))
    text = open(store.path, encoding="utf-8").read()
    assert "[Tab_1]" not in text and "[Tab_2]" not in text
    assert store_at(tmp_path).load().tabs == [TabConfig("Только одна")]
