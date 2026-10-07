import dataclasses
import os
from datetime import datetime

from backup_app.backend.constants import NO_DESTINATION, NO_SOURCES
from backup_app.backend.copier import BackupOptions
from backup_app.backend.scheduler import PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_WEEKLY, Schedule, parse_time
from backup_app.backend.settings_store import AppConfig, SettingsStore, TabConfig, new_tab_uid

BS = chr(92)

# Файл версии 9: расписание и параметры копирования общие, в [General].
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

# Три вкладки версии 9 с недельным расписанием; вторая без папки назначения.
LEGACY_WEEKLY_INI = """[General]
period_type=Еженедельно
backup_time=21:30
weekday=4
monthday=15
keep_history=false
create_backup_folder=false
copy_folder_contents=true
timer_active={timer_active}
copy_all_tabs={copy_all}
active_tab=1
last_backup_time=2026-10-03T21:30:05
timer_started_at=2026-09-01T08:00:00
tab_count=3

[Tab_0]
source_folders=C:/Документы
destination_folder=D:/Копии
tab_title=Документы

[Tab_1]
source_files=C:/отчет.docx
tab_title=Без папки

[Tab_2]
source_folders=C:/Фото
destination_folder=E:/Копии
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


def load_text(tmp_path, text):
    (tmp_path / "settings.ini").write_text(text, encoding="utf-8")
    return store_at(tmp_path).load()


def without_uids(config):
    """Копия настроек с пустыми идентификаторами вкладок: для сравнения с настройками по умолчанию."""
    tabs = [dataclasses.replace(tab, uid="") for tab in config.tabs]
    return dataclasses.replace(config, tabs=tabs)


def test_tab_defaults_problems_schedule_and_options():
    tab = TabConfig()
    assert len(tab.uid) == 12 and tab.uid != TabConfig().uid
    assert tab.title == "Без названия" and tab.schedule_on is False
    assert tab.backup_time == "09:00" and tab.period_type == PERIOD_DAILY
    # у новой вкладки, при первом запуске и после сброса все выключено
    assert tab.options() == BackupOptions(copy_folder_contents=False, keep_history=False, create_backup_folder=False)
    assert tab.options() == BackupOptions()
    app = AppConfig()
    assert not (app.auto_start or app.minimize_to_tray or app.show_notifications or app.run_missed)
    assert tab.problems() == [NO_SOURCES, NO_DESTINATION]
    assert TabConfig(files=["a.txt"]).problems() == [NO_DESTINATION]
    assert TabConfig(destination="D:/x").problems() == [NO_SOURCES]
    assert TabConfig(folders=["C:/a"], destination="D:/x").problems() == []
    weekly = TabConfig(period_type=PERIOD_WEEKLY, backup_time="21:30", weekday=6, monthday=3)
    assert weekly.schedule() == Schedule(PERIOD_WEEKLY, parse_time("21:30"), 6, 3)


def test_app_config_finds_tabs_by_uid():
    first, second = TabConfig(uid="a1"), TabConfig(uid="b2")
    config = AppConfig(active_tab=1, tabs=[first, second])
    assert config.tab("b2") is second and config.tab("нет") is None
    assert config.current_tab() is second


def test_roundtrip_keeps_every_field(tmp_path):
    config = AppConfig(
        auto_start=True, minimize_to_tray=False, show_notifications=False, run_missed=False,
        max_file_size_gb=10, active_tab=1,
        tabs=[
            TabConfig(uid="a1b2c3d4e5f6", title="Документы бухгалтерии",
                      folders=["C:/Исходные данные", "D:/Фото 2026"], files=["C:/Исходные данные/ф.txt"],
                      destination="D:/Копии", schedule_on=True, period_type=PERIOD_WEEKLY, backup_time="21:30",
                      weekday=4, monthday=15, copy_folder_contents=True, create_backup_folder=False,
                      keep_history=False, timer_started_at=datetime(2026, 10, 1, 8, 0, 0),
                      last_backup_time=datetime(2026, 10, 6, 12, 0, 5)),
            TabConfig(uid="second-tab_2", title="Вторая", folders=["C:" + BS + "Папка, с запятой"],
                      files=["@файл"], destination="E:" + BS + "Копии", period_type=PERIOD_MONTHLY,
                      backup_time="07:05", weekday=6, monthday=31),
        ],
    )
    store_at(tmp_path).save(config)
    assert store_at(tmp_path).load() == config


def test_defaults_when_file_missing(tmp_path):
    assert without_uids(store_at(tmp_path, "missing.ini").load()) == without_uids(AppConfig())


def test_new_file_layout(tmp_path):
    """Общие ключи расписания и параметров версии 9 больше не пишутся: они у каждой вкладки."""
    store_at(tmp_path).save(AppConfig(tabs=[TabConfig(uid="a1", title="A", folders=["C:/один"],
                                                      destination="D:/x")]))
    text = (tmp_path / "settings.ini").read_text(encoding="utf-8")
    general, tab = text.split("[Tab_0]")
    for key in ("auto_start", "minimize_to_tray", "show_notifications", "run_missed", "max_file_size_gb",
                "active_tab", "tab_count", "tab_names"):
        assert f"{key}=" in general
    for key in ("period_type", "backup_time", "weekday", "monthday", "copy_folder_contents", "copy_all_tabs",
                "create_backup_folder", "keep_history", "timer_active", "timer_started_at", "last_backup_time"):
        assert f"{key}=" not in general
    for key in ("tab_id", "tab_title", "source_folders", "source_files", "destination_folder", "timer_active",
                "period_type", "backup_time", "weekday", "monthday", "copy_folder_contents",
                "create_backup_folder", "keep_history", "timer_started_at", "last_backup_time"):
        assert f"{key}=" in tab
    assert "tab_id=a1" in tab and "source_folders=C:/один" in tab and "source_files=@Invalid()" in tab
    assert "tab_names=A" in general


def test_legacy_ini_is_compatible(tmp_path):
    config = load_text(tmp_path, LEGACY_INI)
    assert [tab.title for tab in config.tabs] == ["Мои документы", "Фото"]
    first, second = config.tabs
    assert first.folders == ["C:/Users/User/Documents", "C:/Users/User/Desktop"]
    assert first.files == ["C:/Users/User/important.txt"]
    assert first.destination == "D:/Backup"
    assert second.folders == [] and second.destination == ""
    # общее расписание без «копировать все вкладки» достается выбранной вкладке
    assert first.schedule_on is True and second.schedule_on is False
    assert all(tab.backup_time == "09:00" and tab.period_type == PERIOD_DAILY for tab in config.tabs)
    # новые ключи получают значения по умолчанию
    assert not (config.minimize_to_tray or config.show_notifications or config.run_missed)
    assert config.max_file_size_gb == 2 and config.active_tab == 0
    assert first.last_backup_time is None
    assert len({tab.uid for tab in config.tabs}) == 2


def test_legacy_schedule_and_options_are_inherited_by_every_tab(tmp_path):
    config = load_text(tmp_path, LEGACY_WEEKLY_INI.format(timer_active="false", copy_all="false"))
    for tab in config.tabs:
        assert (tab.period_type, tab.backup_time, tab.weekday, tab.monthday) == (PERIOD_WEEKLY, "21:30", 4, 15)
        assert tab.options() == BackupOptions(copy_folder_contents=True, keep_history=False,
                                              create_backup_folder=False)
        assert tab.last_backup_time == datetime(2026, 10, 3, 21, 30, 5)
        assert tab.timer_started_at == datetime(2026, 9, 1, 8, 0, 0)
        assert tab.schedule_on is False


def test_legacy_schedule_for_all_tabs_goes_to_tabs_with_data(tmp_path):
    config = load_text(tmp_path, LEGACY_WEEKLY_INI.format(timer_active="true", copy_all="true"))
    assert [tab.schedule_on for tab in config.tabs] == [True, False, True]


def test_legacy_schedule_without_all_tabs_goes_to_active_tab(tmp_path):
    config = load_text(tmp_path, LEGACY_WEEKLY_INI.format(timer_active="true", copy_all="false"))
    assert config.active_tab == 1
    assert [tab.schedule_on for tab in config.tabs] == [False, True, False]


def test_tab_keys_win_over_legacy_general_keys(tmp_path):
    text = LEGACY_WEEKLY_INI.format(timer_active="true", copy_all="true").replace(
        "tab_title=Фото\n", "tab_title=Фото\ntimer_active=false\nbackup_time=06:15\nkeep_history=true\n"
                          "last_backup_time=\n")
    photos = load_text(tmp_path, text).tabs[2]
    assert photos.schedule_on is False and photos.backup_time == "06:15" and photos.keep_history is True
    assert photos.last_backup_time is None and photos.weekday == 4


def test_tab_uids_are_kept_and_duplicates_regenerated(tmp_path):
    text = ("[General]\ntab_count=4\n"
            "[Tab_0]\ntab_id=a1b2c3d4e5f6\ntab_title=Первая\n"
            "[Tab_1]\ntab_id=a1b2c3d4e5f6\ntab_title=Копия первой\n"
            "[Tab_2]\ntab_id=пробел и кириллица\ntab_title=Плохой id\n"
            "[Tab_3]\ntab_title=Без id\n")
    config = load_text(tmp_path, text)
    uids = [tab.uid for tab in config.tabs]
    assert uids[0] == "a1b2c3d4e5f6"
    assert len(set(uids)) == 4 and all(len(uid) == 12 for uid in uids[1:])
    store_at(tmp_path).save(config)
    assert [tab.uid for tab in store_at(tmp_path).load().tabs] == uids


def test_new_tab_uid_is_short_and_unique():
    uids = {new_tab_uid() for _ in range(200)}
    assert len(uids) == 200 and all(len(uid) == 12 and uid.isalnum() for uid in uids)


def test_single_folder_saved_by_qsettings_is_read(tmp_path):
    """Список из одного пути старые версии сохраняли двоичным блоком @Variant."""
    (tmp_path / "settings.ini").write_bytes(QT_SINGLE_FOLDER_INI.encode("utf-8"))
    tab = store_at(tmp_path).load().tabs[0]
    assert (tab.title, tab.folders, tab.files, tab.destination) == ("Одна папка", ["D:/x"], [], "E:/Backup")


def test_saved_file_is_readable_by_old_versions(tmp_path):
    """Один путь пишется обычной строкой: ее понимает и QSettings, и прежний код."""
    store_at(tmp_path).save(AppConfig(tabs=[TabConfig(title="A", folders=["C:/один"], destination="D:/x")]))
    text = (tmp_path / "settings.ini").read_text(encoding="utf-8")
    assert "source_folders=C:/один" in text
    assert "source_files=@Invalid()" in text
    assert "tab_names=A" in text


def test_shipped_example_ini_loads(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    example = os.path.join(root, "settings_ example.ini")
    with open(example, encoding="utf-8") as handle:
        config = load_text(tmp_path, handle.read())
    assert len(config.tabs) == 1 and config.max_file_size_gb == 2
    tab = config.tabs[0]
    assert tab.backup_time == "09:00" and tab.period_type == PERIOD_DAILY and tab.schedule_on is False
    assert tab.options() == BackupOptions() and tab.uid == "3f2a9c1d7e40"
    assert without_uids(config) == without_uids(AppConfig())  # пример показывает значения по умолчанию


def test_missing_paths_are_kept(tmp_path):
    """Отключенный диск не должен стирать пути из настроек."""
    config = AppConfig(tabs=[TabConfig(title="USB", folders=["X:/нет такого диска"], files=["X:/нет.txt"],
                                       destination="Y:/нет")])
    store_at(tmp_path).save(config)
    assert store_at(tmp_path).load().tabs == config.tabs


def test_invalid_values_fall_back_to_defaults(tmp_path):
    config = load_text(tmp_path, (
        "[General]\nmax_file_size_gb=-5\nactive_tab=7\ntab_count=0\nrun_missed=maybe\n"
        "[Tab_0]\nperiod_type=Bogus\nbackup_time=99:99\nweekday=12\nmonthday=0\n"
        "last_backup_time=yesterday\nkeep_history=maybe\ntimer_active=2\n"))
    assert len(config.tabs) == 1 and config.max_file_size_gb == 2 and config.active_tab == 0
    assert config.run_missed is AppConfig().run_missed is False
    tab = config.tabs[0]
    assert tab.period_type == PERIOD_DAILY and tab.backup_time == "09:00"
    assert tab.weekday == 0 and tab.monthday == 1 and tab.last_backup_time is None
    assert tab.keep_history is TabConfig().keep_history is False and tab.schedule_on is False


def test_reset_restores_defaults(tmp_path):
    store = store_at(tmp_path)
    store.save(AppConfig(run_missed=False, tabs=[TabConfig(title="A", schedule_on=True), TabConfig(title="B")]))
    assert without_uids(store.reset()) == without_uids(AppConfig())
    assert without_uids(store_at(tmp_path).load()) == without_uids(AppConfig())


def test_save_removes_stale_tab_sections(tmp_path):
    store = store_at(tmp_path)
    store.save(AppConfig(tabs=[TabConfig(title="A"), TabConfig(title="B"), TabConfig(title="C")]))
    only = TabConfig(title="Только одна")
    store.save(AppConfig(tabs=[only]))
    text = open(store.path, encoding="utf-8").read()
    assert "[Tab_1]" not in text and "[Tab_2]" not in text
    assert store_at(tmp_path).load().tabs == [only]
