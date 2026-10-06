import os

from backup_app.frontend.single_instance import SingleInstance
from helpers import wait_for


def test_second_instance_asks_first_to_show(qapp):
    key = f"backupapp-test-{os.getpid()}"
    first = SingleInstance(key)
    try:
        assert first.try_acquire() is True
        assert first.is_primary
        received = []
        first.activated.connect(lambda: received.append(True))

        second = SingleInstance(key)
        assert second.try_acquire() is False
        assert not second.is_primary
        assert wait_for(qapp, lambda: bool(received), timeout=5)
    finally:
        first.release()


def test_key_is_free_after_release(qapp):
    key = f"backupapp-test-release-{os.getpid()}"
    first = SingleInstance(key)
    assert first.try_acquire()
    first.release()
    again = SingleInstance(key)
    try:
        assert again.try_acquire()
    finally:
        again.release()
