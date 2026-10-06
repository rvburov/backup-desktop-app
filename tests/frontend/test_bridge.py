"""События из фоновых потоков бэкенда приходят в поток интерфейса."""
import threading

from backup_app.backend import BackupService, ScheduleChanged, SettingsStore
from backup_app.frontend.bridge import ServiceBridge
from helpers import wait_for


def test_events_from_background_thread_arrive_in_gui_thread(qapp, tmp_path):
    service = BackupService(SettingsStore(str(tmp_path / "settings.ini")))
    bridge = ServiceBridge(service)
    received = []
    bridge.event_received.connect(
        lambda event: received.append((event, threading.current_thread() is threading.main_thread())))
    try:
        worker = threading.Thread(target=lambda: service._emit(ScheduleChanged(())))
        worker.start()
        worker.join()
        assert wait_for(qapp, lambda: received, timeout=5)
        assert received == [(ScheduleChanged(()), True)]
    finally:
        bridge.close()


def test_events_stop_after_close(qapp, tmp_path):
    service = BackupService(SettingsStore(str(tmp_path / "settings.ini")))
    bridge = ServiceBridge(service)
    received = []
    bridge.event_received.connect(received.append)
    bridge.close()
    service._emit(ScheduleChanged(()))
    qapp.processEvents()
    assert received == []
