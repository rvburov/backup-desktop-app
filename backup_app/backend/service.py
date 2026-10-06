"""Сервис резервного копирования: единственная точка входа в бэкенд.

Сервис владеет настройками, расписанием, проверками и запуском копирования. Планировщик
и копирование работают в фоновых потоках. О происходящем сервис сообщает событиями
(модуль events), на которые подписывается интерфейс. Об интерфейсе сервис ничего не знает
и работает без Qt, поэтому его можно запускать и тестировать без окна.
"""
import copy
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

from . import autostart as autostart_module
from . import safety
from .constants import CHECK_INTERVAL_SECONDS, MISSED_RUN_DELAY_SECONDS
from .copier import (STATUS_CANCELLED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL, BackupJob,
                     BackupOptions, BackupResult, BackupRunner)
from .events import (BackupFinished, BackupProgress, BackupStarted, ConfigChanged, RunSkipped,
                     ScheduleChanged)
from .logger import get_logger
from .scheduler import format_run_time, next_run, previous_run
from .settings_store import EDITABLE_FIELDS, AppConfig, SettingsStore, TabConfig

Listener = Callable[[object], None]

ALREADY_RUNNING = "Копирование уже выполняется, новый запуск пропущен"
NO_TABS_WITH_DATA = "Нет вкладок с данными для копирования"
NO_SOURCES = "Не выбраны исходные файлы и папки"
NO_DESTINATION = "Не выбрана папка назначения"


class BackupService:
    def __init__(self, store: SettingsStore, *, now: Optional[Callable[[], datetime]] = None,
                 check_interval: float = CHECK_INTERVAL_SECONDS,
                 missed_run_delay: float = MISSED_RUN_DELAY_SECONDS,
                 autostart=autostart_module, log_path: Optional[str] = None):
        self._store = store
        self._now = now or datetime.now
        self._check_interval = check_interval
        self._missed_run_delay = missed_run_delay
        self._autostart = autostart
        self._log_path = log_path
        self._protected = safety.ProtectedPaths(safety.system_paths())
        self.log = get_logger()

        self._lock = threading.RLock()
        self._config = store.load()
        self._listeners: List[Listener] = []
        self._schedule_active = False
        self._next_run: Optional[datetime] = None
        self._missed_run_due: Optional[datetime] = None
        self._runner: Optional[BackupRunner] = None
        self._run_thread: Optional[threading.Thread] = None
        self._idle = threading.Event()
        self._idle.set()
        self._started = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None

    # ----------------------------------------------------------- подписка
    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _emit(self, *events) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for event in events:
            for listener in listeners:
                try:
                    listener(event)
                except Exception:  # защитный код: сбой подписчика не ломает сервис
                    self.log.exception("Ошибка обработчика события")

    # ----------------------------------------------------------- состояние
    @property
    def settings_path(self) -> str:
        return self._store.path

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return copy.deepcopy(self._config)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._runner is not None

    @property
    def schedule_active(self) -> bool:
        with self._lock:
            return self._schedule_active

    @property
    def next_run(self) -> Optional[datetime]:
        with self._lock:
            return self._next_run

    # ---------------------------------------------------------- жизненный цикл
    def start(self, run_scheduler: bool = True) -> None:
        """Синхронизирует автозапуск, возобновляет расписание и запускает планировщик."""
        with self._lock:
            if self._started:
                return
            self._started = True
        self.log.info(f"Файл настроек: {self._store.path}")
        if self._log_path:
            self.log.info(f"Файл журнала: {self._log_path}")
        if not os.path.exists(self._store.path):
            with self._lock:
                self._save()  # первый запуск: файл настроек появляется сразу
        events = self._sync_autostart() + self._resume_schedule()
        self._emit(*events)
        if run_scheduler:
            self._stop.clear()
            self._scheduler_thread = threading.Thread(target=self._scheduler_loop, name="backup-scheduler",
                                                      daemon=True)
            self._scheduler_thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Останавливает планировщик и текущее копирование, сохраняет настройки."""
        self._stop.set()
        self._wake.set()
        scheduler = self._scheduler_thread
        if scheduler is not None and scheduler is not threading.current_thread():
            scheduler.join(timeout)
        self._scheduler_thread = None
        with self._lock:
            runner, run_thread = self._runner, self._run_thread
        if runner is not None:
            self.log.warning("Копирование прервано при выходе из приложения")
            runner.cancel()
            if run_thread is not None and run_thread is not threading.current_thread():
                run_thread.join(timeout)
        with self._lock:
            self._save()
        self.log.info("Приложение завершает работу")

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Ждёт окончания текущего копирования."""
        return self._idle.wait(timeout)

    # ------------------------------------------------------------ настройки
    def update_config(self, config: AppConfig) -> None:
        """Принимает изменения из окна. Служебные поля (расписание, автозапуск) не меняются."""
        event = None
        with self._lock:
            for name in EDITABLE_FIELDS:
                setattr(self._config, name, copy.deepcopy(getattr(config, name)))
            self._normalize()
            self._save()
            if self._schedule_active:
                upcoming = next_run(self._config.schedule(), self._now())
                if upcoming != self._next_run:
                    self._next_run = upcoming
                    event = ScheduleChanged(True, upcoming)
        if event is not None:
            self._wake.set()
            self._emit(event)

    def set_autostart(self, enabled: bool) -> None:
        """Включает или выключает автозапуск. При ошибке бросает исключение."""
        try:
            if enabled:
                self._autostart.enable()
            else:
                self._autostart.disable()
        except Exception as error:
            self.log.error(f"Не удалось изменить автозапуск: {error}")
            raise
        with self._lock:
            self._config.auto_start = bool(enabled)
            self._save()
        if enabled:
            self.log.info("Автозапуск при входе в систему включён (приложение будет стартовать в трей)")
        else:
            self.log.info("Автозапуск при входе в систему отключён")

    def reset(self) -> AppConfig:
        """Останавливает расписание, отключает автозапуск и записывает настройки по умолчанию."""
        try:
            self._autostart.disable()
        except Exception as error:
            self.log.error(f"Не удалось отключить автозапуск: {error}")
        with self._lock:
            self._schedule_active = False
            self._next_run = None
            self._missed_run_due = None
            try:
                self._config = self._store.reset()
            except OSError as error:
                self.log.error(f"Не удалось сохранить настройки: {error}")
                self._config = AppConfig()
            config = copy.deepcopy(self._config)
        self.log.info("Все настройки сброшены к значениям по умолчанию")
        self._emit(ConfigChanged(config), ScheduleChanged(False, None))
        return config

    # ------------------------------------------------------------- проверки
    def problems(self) -> List[str]:
        """Что мешает запустить копирование с текущими настройками."""
        with self._lock:
            return self._build_jobs(self._config)[1]

    def source_problem(self, path: str) -> Optional[str]:
        return safety.source_problem(path, self._protected)

    def destination_problem(self, path: str) -> Optional[str]:
        return safety.destination_problem(path, self._protected)

    def path_problem(self, path: str) -> Optional[str]:
        return safety.path_problem(path, self._protected)

    # ------------------------------------------------------------ расписание
    def start_schedule(self) -> List[str]:
        """Включает расписание. Возвращает список проблем, если включить нельзя."""
        with self._lock:
            problems = self._build_jobs(self._config)[1]
            if problems:
                return problems
            now = self._now()
            self._config.timer_started_at = now.replace(microsecond=0)
            self._activate(now)
            self._save()
            upcoming, period = self._next_run, self._config.period_type
        self.log.info(f"Автоматическое копирование запущено. Период: {period}, "
                      f"следующее: {format_run_time(upcoming)}")
        self._wake.set()
        self._emit(ScheduleChanged(True, upcoming))
        return []

    def stop_schedule(self) -> None:
        with self._lock:
            self._schedule_active = False
            self._next_run = None
            self._missed_run_due = None
            self._config.timer_active = False
            self._save()
        self.log.info("Автоматическое копирование остановлено")
        self._emit(ScheduleChanged(False, None))

    def tick(self, now: Optional[datetime] = None) -> bool:
        """Проверка расписания. Вызывается планировщиком; True, если копирование было запрошено."""
        now = now or self._now()
        event = None
        with self._lock:
            missed_due = self._missed_run_due is not None and now >= self._missed_run_due
            if missed_due:
                self._missed_run_due = None
            scheduled_due = self._schedule_active and self._next_run is not None and now >= self._next_run
            if scheduled_due:
                self._next_run = next_run(self._config.schedule(), now)
                event = ScheduleChanged(True, self._next_run)
        if event is not None:
            self._emit(event)
        if missed_due or scheduled_due:
            self.run_now(scheduled=True)
            return True
        return False

    # ------------------------------------------------------------ копирование
    def run_now(self, scheduled: bool = False) -> List[str]:
        """Запускает копирование в фоне. Возвращает список проблем, если запуск невозможен."""
        thread = None
        messages: List[Tuple[int, str]] = []
        with self._lock:
            if self._runner is not None:
                problems = [ALREADY_RUNNING]
                event = RunSkipped(scheduled, ALREADY_RUNNING)
                messages.append((logging.WARNING, ALREADY_RUNNING))
            else:
                jobs, problems = self._build_jobs(self._config)
                if problems:
                    event = RunSkipped(scheduled, "; ".join(problems))
                    if scheduled:
                        messages.append((logging.WARNING, f"Плановое копирование не запущено: {event.reason}"))
                else:
                    runner = BackupRunner(jobs, self._options(), self._policy(), on_progress=self._on_progress)
                    thread = threading.Thread(target=self._run_backup, args=(runner, scheduled),
                                              name="backup-runner", daemon=True)
                    self._runner, self._run_thread = runner, thread
                    self._idle.clear()
                    names = tuple(job.name for job in jobs)
                    event = BackupStarted(scheduled, names)
                    kind = "плановое" if scheduled else "ручное"
                    messages.append((logging.INFO, f"Начато {kind} копирование: {', '.join(names)}"))
        for level, text in messages:
            self.log.log(level, text)
        self._emit(event)
        if thread is not None:
            thread.start()
        return problems

    def cancel(self) -> None:
        with self._lock:
            runner = self._runner
        if runner is not None:
            runner.cancel()
            self.log.info("Запрошена отмена копирования")

    # ------------------------------------------------------------- внутреннее
    def _run_backup(self, runner: BackupRunner, scheduled: bool) -> None:
        try:
            result = runner.run()
        except Exception as error:  # защитный код: поток не должен умереть молча
            self.log.exception("Критическая ошибка копирования")
            result = BackupResult(status=STATUS_FAILED, message=f"Критическая ошибка: {error}",
                                  errors=[str(error)])
        with self._lock:
            self._runner, self._run_thread = None, None
            if result.status in (STATUS_OK, STATUS_PARTIAL):
                self._config.last_backup_time = self._now().replace(microsecond=0)
            self._save()
        self._log_result(result)
        self._emit(BackupFinished(result, scheduled))
        self._idle.set()

    def _log_result(self, result: BackupResult) -> None:
        if result.status == STATUS_OK:
            self.log.info(f"✓ {result.message}")
        elif result.status == STATUS_PARTIAL:
            self.log.warning(f"⚠ {result.message}")
        elif result.status == STATUS_CANCELLED:
            self.log.warning(f"✗ {result.message}")
        else:
            self.log.error(f"✗ {result.message}")

    def _on_progress(self, percent: int, text: str) -> None:
        self._emit(BackupProgress(percent, text))

    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.tick()
            except Exception:  # защитный код: планировщик не должен останавливаться
                self.log.exception("Ошибка планировщика")
            self._wake.wait(self._seconds_until_check())

    def _seconds_until_check(self) -> float:
        now = self._now()
        with self._lock:
            due = [moment for moment in (self._next_run if self._schedule_active else None, self._missed_run_due)
                   if moment is not None]
        wait = self._check_interval
        for moment in due:
            wait = min(wait, max(0.2, (moment - now).total_seconds()))
        return wait

    def _sync_autostart(self) -> list:
        try:
            actual = bool(self._autostart.is_enabled())
        except Exception as error:
            self.log.warning(f"Не удалось проверить автозапуск: {error}")
            return []
        with self._lock:
            if actual == self._config.auto_start:
                return []
            self._config.auto_start = actual
            self._save()
            config = copy.deepcopy(self._config)
        self.log.info("Состояние автозапуска в системе отличалось от настроек, синхронизировано")
        return [ConfigChanged(config)]

    def _resume_schedule(self) -> list:
        """Возобновляет расписание после запуска и планирует пропущенное копирование."""
        missed = False
        with self._lock:
            if not self._config.timer_active:
                return []
            problems = self._build_jobs(self._config)[1]
            if problems:
                self._config.timer_active = False
                self._save()
                event = ScheduleChanged(False, None)
            else:
                now = self._now()
                self._activate(now)
                missed = self._config.run_missed and self._missed_run_pending(now)
                if missed:
                    self._missed_run_due = now + timedelta(seconds=self._missed_run_delay)
                self._save()
                event = ScheduleChanged(True, self._next_run)
        if problems:
            self.log.warning("Расписание не возобновлено: " + "; ".join(problems))
        else:
            self.log.info(f"Расписание возобновлено, следующее копирование: {format_run_time(event.next_run)}")
            if missed:
                self.log.info("Назначенное время было пропущено, копирование будет выполнено сейчас")
        return [event]

    def _missed_run_pending(self, now: datetime) -> bool:
        previous = previous_run(self._config.schedule(), now)
        marks = [mark for mark in (self._config.last_backup_time, self._config.timer_started_at) if mark]
        return bool(marks) and max(marks) < previous

    def _activate(self, now: datetime) -> None:
        self._schedule_active = True
        self._config.timer_active = True
        self._next_run = next_run(self._config.schedule(), now)

    def _normalize(self) -> None:
        config = self._config
        if not config.tabs:
            config.tabs = [TabConfig()]
        if not 0 <= config.active_tab < len(config.tabs):
            config.active_tab = 0
        config.max_file_size_gb = max(0, int(config.max_file_size_gb))

    def _save(self) -> None:
        try:
            self._store.save(self._config)
        except OSError as error:
            self.log.error(f"Не удалось сохранить настройки: {error}")

    def _options(self) -> BackupOptions:
        config = self._config
        return BackupOptions(copy_folder_contents=config.copy_folder_contents,
                             keep_history=config.keep_history,
                             create_backup_folder=config.create_backup_folder)

    def _policy(self) -> safety.SafetyPolicy:
        return safety.SafetyPolicy(max_file_size=max(0, self._config.max_file_size_gb) * safety.GB,
                                   protected_paths=self._protected.paths)

    @staticmethod
    def _build_jobs(config: AppConfig) -> Tuple[List[BackupJob], List[str]]:
        jobs: List[BackupJob] = []
        problems: List[str] = []
        if config.copy_all_tabs:
            for tab in config.tabs:
                if tab.has_sources() and tab.destination:
                    jobs.append(_job_from(tab))
            if not jobs:
                problems.append(NO_TABS_WITH_DATA)
            return jobs, problems
        tab = config.current_tab()
        if not tab.has_sources():
            problems.append(NO_SOURCES)
        if not tab.destination:
            problems.append(NO_DESTINATION)
        if not problems:
            jobs.append(_job_from(tab))
        return jobs, problems


def _job_from(tab: TabConfig) -> BackupJob:
    return BackupJob(name=tab.title, folders=list(tab.folders), files=list(tab.files),
                     destination=tab.destination)
