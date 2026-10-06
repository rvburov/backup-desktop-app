"""События и журнал из фоновых потоков бэкенда приходят в поток интерфейса."""
import threading

from backup_app.backend import BackupService, ScheduleChanged, SettingsStore, get_logger
from backup_app.frontend.bridge import ServiceBridge
from helpers import wait_for


def test_events_from_background_thread_arrive_in_gui_thread(qapp, tmp_path):
    service = BackupService(SettingsStore(str(tmp_path / "settings.ini")))
    bridge = ServiceBridge(service)
    received = []
    bridge.event_received.connect(
        lambda event: received.append((event, threading.current_thread() is threading.main_thread())))
    try:
        worker = threading.Thread(target=lambda: service._emit(ScheduleChanged(False, None)))
        worker.start()
        worker.join()
        assert wait_for(qapp, lambda: received, timeout=5)
        assert received == [(ScheduleChanged(False, None), True)]
    finally:
        bridge.close()


def test_log_records_reach_the_window_and_stop_after_close(qapp, tmp_path):
    service = BackupService(SettingsStore(str(tmp_path / "settings.ini")))
    bridge = ServiceBridge(service)
    lines = []
    bridge.log_message.connect(lines.append)
    worker = threading.Thread(target=lambda: get_logger().info("запись из фонового потока"))
    worker.start()
    worker.join()
    assert wait_for(qapp, lambda: lines, timeout=5)
    assert lines[0].endswith("запись из фонового потока") and lines[0].startswith("[")
    bridge.close()
    get_logger().info("после закрытия")
    qapp.processEvents()
    assert len(lines) == 1
