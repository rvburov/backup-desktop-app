"""Сервис резервного копирования: единственная точка входа в бэкенд.

Сервис владеет настройками, расписанием, проверками и запуском копирования. Планировщик
и копирование работают в фоновых потоках. О происходящем сервис сообщает событиями
(модуль events), на которые подписывается интерфейс. Об интерфейсе сервис ничего не знает
и работает без Qt, поэтому его можно запускать и тестировать без окна.

Расписание и параметры копирования у каждой вкладки свои. Включает и выключает расписание
вкладки только сервис (set_tab_schedule). Вкладки, чье время подошло в одну проверку,
копируются вместе одним копированием.

Для пользователя сервис ведет историю копирования (модуль history): начало и итог каждого
копирования, ошибки по файлам, пропуски по расписанию, запуск и остановку расписания.
Записи о вкладках хранят их идентификаторы. Все остальное пишется только в подробный журнал.
"""
import copy
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import autostart as autostart_module
from . import safety
from .constants import (CHECK_INTERVAL_SECONDS, HISTORY_FILE_NAME, MISSED_RUN_DELAY_SECONDS, NO_DESTINATION,
                        NO_SOURCES)
from .copier import STATUS_CANCELLED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL, BackupJob, BackupResult, BackupRunner
from .events import (AppProblem, BackupFinished, BackupProgress, BackupStarted, ConfigChanged, HistoryAdded,
                     RunSkipped, ScheduleChanged)
from .history import ICON_ERROR, ICON_OK, ICON_WARNING, TIME_FORMAT, HistoryEntry, HistoryStore, limit_details
from .logger import get_logger
from .scheduler import format_run_time, next_run, previous_run
from .settings_store import EDITABLE_FIELDS, SERVICE_TAB_FIELDS, AppConfig, SettingsStore, TabConfig, new_tab_uid
from .wording import count_files

Listener = Callable[[object], None]
Record = Tuple[str, Tuple[str, ...]]  # текст записи истории и вкладки записи

ALREADY_RUNNING = "Копирование уже выполняется, новый запуск пропущен"
NO_TABS_WITH_DATA = "Нет вкладок с данными для копирования"
SCHEDULED_WHILE_RUNNING = "в это время шло другое копирование"
RESULT_ICONS = {STATUS_OK: ICON_OK, STATUS_PARTIAL: ICON_WARNING}

__all__ = ["ALREADY_RUNNING", "NO_DESTINATION", "NO_SOURCES", "NO_TABS_WITH_DATA", "SCHEDULED_WHILE_RUNNING",
           "BackupService"]


class BackupService:
    def __init__(self, store: SettingsStore, *, now: Optional[Callable[[], datetime]] = None,
                 check_interval: float = CHECK_INTERVAL_SECONDS,
                 missed_run_delay: float = MISSED_RUN_DELAY_SECONDS,
                 autostart=autostart_module, log_path: Optional[str] = None,
                 history: Optional[HistoryStore] = None):
        self._store = store
        self._now = now or datetime.now
        self._check_interval = check_interval
        self._missed_run_delay = missed_run_delay
        self._autostart = autostart
        self._log_path = log_path
        self._history = history or HistoryStore(
            os.path.join(os.path.dirname(os.path.abspath(store.path)), HISTORY_FILE_NAME), now=self._now)
        self._settings_write_failed = False
        self._protected = safety.ProtectedPaths(safety.system_paths())
        self.log = get_logger()

        self._lock = threading.RLock()
        self._config = store.load()
        self._listeners: List[Listener] = []
        # События, возникшие под блокировкой: уходят подписчикам при ближайшем _emit.
        self._pending_events: list = []
        # ScheduleChanged рассылает один поток за раз, снимок берется перед каждой рассылкой.
        self._schedule_dirty = False
        self._schedule_emitting = False
        # Следующее копирование каждой вкладки, чье расписание работает (включено и возобновлено).
        self._next_runs: Dict[str, datetime] = {}
        self._missed_run_due: Optional[datetime] = None
        self._missed_tabs: List[str] = []
        self._runner: Optional[BackupRunner] = None
        self._run_thread: Optional[threading.Thread] = None
        self._run_tabs: Tuple[str, ...] = ()
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
        """Рассылает события подписчикам; вызывается вне блокировки. Сначала уходят отложенные события."""
        with self._lock:
            listeners = list(self._listeners)
            pending, self._pending_events = self._pending_events, []
        for event in (*pending, *events):
            for listener in listeners:
                try:
                    listener(event)
                except Exception:  # защитный код: сбой подписчика не ломает сервис
                    self.log.exception("Ошибка обработчика события")

    def _emit_schedule(self) -> None:
        """Сообщает о текущем расписании вкладок. Вызывается вне блокировки.

        Снимок расписания берется прямо перед рассылкой, а рассылает их один поток за раз:
        если расписание меняется во время рассылки, тот же поток отправляет еще один снимок.
        Поэтому последним подписчики всегда получают действующее расписание.
        """
        with self._lock:
            self._schedule_dirty = True
            if self._schedule_emitting:
                return
            self._schedule_emitting = True
        try:
            while True:
                with self._lock:
                    if not self._schedule_dirty:
                        break
                    self._schedule_dirty = False
                    event = self._schedule_event()
                self._emit(event)
        finally:
            with self._lock:
                self._schedule_emitting = False

    # ----------------------------------------------------------- состояние
    @property
    def settings_path(self) -> str:
        return self._store.path

    @property
    def log_path(self) -> Optional[str]:
        """Файл подробного журнала или None, если журнал не ведется."""
        return self._log_path

    @property
    def history_path(self) -> str:
        return self._history.path

    def history(self) -> List[HistoryEntry]:
        """История копирования за срок хранения, от старых записей к новым."""
        return self._history.entries()

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return copy.deepcopy(self._config)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._runner is not None

    @property
    def running_tabs(self) -> Tuple[str, ...]:
        """Идентификаторы вкладок текущего копирования, пустой кортеж, если копирования нет."""
        with self._lock:
            return self._run_tabs

    @property
    def schedule_active(self) -> bool:
        """Расписание работает хотя бы у одной вкладки."""
        with self._lock:
            return bool(self._next_runs)

    @property
    def next_run(self) -> Optional[datetime]:
        """Ближайшее копирование по расписанию среди всех вкладок или None."""
        with self._lock:
            return min(self._next_runs.values(), default=None)

    def next_runs(self) -> Dict[str, datetime]:
        """Следующее копирование каждой вкладки, чье расписание работает: {идентификатор: время}."""
        with self._lock:
            return dict(self._next_runs)

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
        events = self._sync_autostart()
        resumed = self._resume_schedule()
        self._emit(*events)
        if resumed:
            self._emit_schedule()
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
            runner, run_thread, run_tabs = self._runner, self._run_thread, self._run_tabs
        if runner is not None:
            self.log.warning("Копирование прервано при выходе из приложения")
            runner.cancel()
            if run_thread is not None and run_thread is not threading.current_thread():
                run_thread.join(timeout)
            if runner.result.status == STATUS_CANCELLED or (run_thread is not None and run_thread.is_alive()):
                self._record(f"{ICON_ERROR} Копирование прервано при выходе из приложения, "
                             f"скопировано {count_files(runner.result.copied_count)}", tab_ids=run_tabs)
        with self._lock:
            self._save()
        self._emit()  # сбой записи настроек
        self.log.info("Приложение завершает работу")

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Ждет окончания текущего копирования."""
        return self._idle.wait(timeout)

    # ------------------------------------------------------------ настройки
    def update_config(self, config: AppConfig) -> None:
        """Принимает изменения из окна.

        Служебные поля (автозапуск, включенное расписание вкладок и их отметки времени) окно
        не меняет: они берутся из копии сервиса по идентификатору вкладки. Если у вкладки с
        работающим расписанием изменились период, время или день, следующее копирование
        пересчитывается. Удаление вкладки с включенным расписанием останавливает его.
        """
        with self._lock:
            old_tabs = {tab.uid: tab for tab in self._config.tabs}
            for name in EDITABLE_FIELDS:
                setattr(self._config, name, copy.deepcopy(getattr(config, name)))
            self._normalize()
            changed = self._merge_tabs(old_tabs)
            stopped = [tab for uid, tab in old_tabs.items()
                       if (tab.schedule_on or uid in self._next_runs) and self._config.tab(uid) is None]
            for tab in stopped:
                self._forget_schedule(tab.uid)
            self._save()
        for tab in stopped:
            self.log.info(f"Автоматическое копирование остановлено: вкладка «{tab.title}» удалена")
            self._record(f"Расписание остановлено: {tab.title}", tab_ids=(tab.uid,))
        if changed or stopped:
            self._wake.set()
            self._emit_schedule()
        else:
            self._emit()  # сбой записи настроек

    def _merge_tabs(self, old_tabs: Dict[str, TabConfig]) -> bool:
        """Переносит служебные поля вкладок из прежней копии. True, если расписание сдвинулось."""
        now = self._now()
        changed = False
        for tab in self._config.tabs:
            old = old_tabs.get(tab.uid) or TabConfig(uid=tab.uid)
            for name in SERVICE_TAB_FIELDS:
                setattr(tab, name, copy.deepcopy(getattr(old, name)))
            if tab.uid in self._next_runs and tab.schedule() != old.schedule():
                self._next_runs[tab.uid] = next_run(tab.schedule(), now)
                changed = True
        return changed

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
        self._emit()  # сбой записи настроек
        if enabled:
            self.log.info("Автозапуск при входе в систему включен (приложение будет стартовать в трей)")
        else:
            self.log.info("Автозапуск при входе в систему отключен")

    def reset(self) -> AppConfig:
        """Останавливает расписание всех вкладок, отключает автозапуск и записывает настройки по умолчанию."""
        events: list = []
        try:
            self._autostart.disable()
        except Exception as error:
            self.log.error(f"Не удалось отключить автозапуск: {error}")
            events.append(AppProblem("Не удалось отключить автозапуск", str(error)))
        with self._lock:
            was_active = bool(self._next_runs) or any(tab.schedule_on for tab in self._config.tabs)
            self._next_runs.clear()
            self._missed_tabs = []
            self._missed_run_due = None
            try:
                self._config = self._store.reset()
            except OSError as error:
                self._config = AppConfig()
                self._settings_not_saved(error)
            config = copy.deepcopy(self._config)
        self.log.info("Все настройки сброшены к значениям по умолчанию")
        if was_active:
            self._record("Расписание остановлено: настройки сброшены")
        self._emit(*events, ConfigChanged(config))
        self._emit_schedule()
        return config

    # ------------------------------------------------------------- проверки
    def problems(self, tab_id: Optional[str] = None) -> List[str]:
        """Что мешает копированию: вкладки tab_id или, без него, всех вкладок вместе."""
        with self._lock:
            if tab_id is None:
                return [] if any(not tab.problems() for tab in self._config.tabs) else [NO_TABS_WITH_DATA]
            tab = self._config.tab(tab_id)
            return tab.problems() if tab is not None else [NO_TABS_WITH_DATA]

    def source_problem(self, path: str) -> Optional[str]:
        return safety.source_problem(path, self._protected)

    def destination_problem(self, path: str) -> Optional[str]:
        return safety.destination_problem(path, self._protected)

    def path_problem(self, path: str) -> Optional[str]:
        return safety.path_problem(path, self._protected)

    # ------------------------------------------------------------ расписание
    def set_tab_schedule(self, tab_id: str, enabled: bool) -> List[str]:
        """Включает или выключает расписание вкладки. Возвращает проблемы, если включить нельзя."""
        if enabled:
            return self._enable_schedule(tab_id)
        self._disable_schedule(tab_id)
        return []

    def _enable_schedule(self, tab_id: str) -> List[str]:
        with self._lock:
            tab = self._config.tab(tab_id)
            if tab is None:
                self.log.warning(f"Расписание не включено: нет вкладки {tab_id}")
                return []
            problems = tab.problems()
            if problems:
                return problems
            if tab.uid in self._next_runs:
                return []
            now = self._now()
            tab.schedule_on = True
            tab.timer_started_at = now.replace(microsecond=0)
            self._next_runs[tab.uid] = upcoming = next_run(tab.schedule(), now)
            self._save()
            title, period = tab.title, tab.period_type
        self.log.info(f"Автоматическое копирование запущено ({title}). Период: {period}, "
                      f"следующее: {format_run_time(upcoming)}")
        self._record(f"Расписание запущено: {title}, следующее копирование: {upcoming.strftime(TIME_FORMAT)}",
                     tab_ids=(tab_id,))
        self._wake.set()
        self._emit_schedule()
        return []

    def _disable_schedule(self, tab_id: str) -> None:
        with self._lock:
            tab = self._config.tab(tab_id)
            was_on = tab is not None and (tab.schedule_on or tab.uid in self._next_runs)
            self._forget_schedule(tab_id)
            if tab is not None:
                tab.schedule_on = False
                self._save()
            title = tab.title if tab else tab_id
        if was_on:
            self.log.info(f"Автоматическое копирование остановлено ({title})")
            self._record(f"Расписание остановлено: {title}", tab_ids=(tab_id,))
        self._emit_schedule()

    def _forget_schedule(self, tab_id: str) -> None:
        """Убирает вкладку из работающего расписания и из пропущенного копирования."""
        self._next_runs.pop(tab_id, None)
        if tab_id in self._missed_tabs:
            self._missed_tabs.remove(tab_id)
            if not self._missed_tabs:
                self._missed_run_due = None

    def tick(self, now: Optional[datetime] = None) -> bool:
        """Проверка расписания. Вызывается планировщиком; True, если копирование было запрошено.

        Все вкладки, чье время подошло, и вкладки с пропущенным копированием запускаются вместе.
        """
        now = now or self._now()
        with self._lock:
            due = [uid for uid, moment in self._next_runs.items() if now >= moment]
            for uid in due:
                self._next_runs[uid] = next_run(self._config.tab(uid).schedule(), now)
            advanced = bool(due)
            if self._missed_run_due is not None and now >= self._missed_run_due:
                due += [uid for uid in self._missed_tabs if uid not in due]
                self._missed_tabs, self._missed_run_due = [], None
            tab_ids = [tab.uid for tab in self._config.tabs if tab.uid in due]
        if advanced:
            self._emit_schedule()
        if tab_ids:
            self.run_now(tab_ids, scheduled=True)
            return True
        return False

    # ------------------------------------------------------------ копирование
    def run_now(self, tab_ids: Optional[Sequence[str]] = None, scheduled: bool = False) -> List[str]:
        """Запускает копирование вкладок в фоне. Возвращает список проблем, если запуск невозможен.

        tab_ids=None означает все вкладки: вкладки без данных молча пропускаются. Одна вкладка
        с проблемами не копируется, и возвращаются ее проблемы. При плановом копировании о
        каждой вкладке, которую скопировать нельзя, делается запись в истории, остальные копируются.
        """
        thread = None
        events: list = []
        records: List[Record] = []
        messages: List[Tuple[int, str]] = []
        with self._lock:
            tabs = self._requested_tabs(tab_ids)
            if self._runner is not None:
                problems = [ALREADY_RUNNING]
                events.append(RunSkipped(scheduled, ALREADY_RUNNING))
                messages.append((logging.WARNING, ALREADY_RUNNING))
                if scheduled:
                    records += [(f"{ICON_WARNING} Плановое копирование не запущено: {SCHEDULED_WHILE_RUNNING} "
                                 f"({tab.title})", (tab.uid,)) for tab in tabs]
            else:
                ready = [tab for tab in tabs if not tab.problems()]
                refused = [tab for tab in tabs if tab.problems()]
                problems = [] if ready else (refused[0].problems() if len(tabs) == 1 else [NO_TABS_WITH_DATA])
                if scheduled:
                    for tab in refused:
                        reason = "; ".join(tab.problems())
                        events.append(RunSkipped(True, reason))
                        messages.append((logging.WARNING, f"Плановое копирование не запущено ({tab.title}): {reason}"))
                        records.append((f"{ICON_ERROR} Плановое копирование не запущено ({tab.title}): {reason}",
                                        (tab.uid,)))
                if ready:
                    thread = self._start_run(ready, scheduled, events, records, messages)
                elif not (scheduled and refused):
                    reason = "; ".join(problems)
                    events.append(RunSkipped(scheduled, reason))
                    if scheduled:
                        messages.append((logging.WARNING, f"Плановое копирование не запущено: {reason}"))
                        records.append((f"{ICON_ERROR} Плановое копирование не запущено: {reason}", ()))
        for level, text in messages:
            self.log.log(level, text)
        self._emit(*events)
        for text, ids in records:
            self._record(text, tab_ids=ids)
        if thread is not None:
            thread.start()
        return problems

    def _requested_tabs(self, tab_ids: Optional[Sequence[str]]) -> List[TabConfig]:
        """Вкладки запуска в порядке вкладок окна. Без tab_ids: все вкладки с данными."""
        if tab_ids is None:
            return [tab for tab in self._config.tabs if not tab.problems()]
        wanted = {tab_ids} if isinstance(tab_ids, str) else set(tab_ids)
        return [tab for tab in self._config.tabs if tab.uid in wanted]

    def _start_run(self, tabs: List[TabConfig], scheduled: bool, events: list, records: List[Record],
                   messages: List[Tuple[int, str]]) -> threading.Thread:
        """Создает копирование вкладок; поток запускает вызывающий после выхода из блокировки."""
        jobs = [_job_from(tab) for tab in tabs]
        tab_ids = tuple(tab.uid for tab in tabs)
        runner = BackupRunner(jobs, policy=self._policy(), on_progress=self._on_progress)
        thread = threading.Thread(target=self._run_backup, args=(runner, scheduled, tab_ids),
                                  name="backup-runner", daemon=True)
        self._runner, self._run_thread, self._run_tabs = runner, thread, tab_ids
        self._idle.clear()
        names = tuple(job.name for job in jobs)
        events.append(BackupStarted(scheduled, names, tab_ids))
        kind = "плановое" if scheduled else "ручное"
        messages.append((logging.INFO, f"Начато {kind} копирование: {', '.join(names)}"))
        records.append((f"{'Плановое' if scheduled else 'Ручное'} копирование: {', '.join(names)}", tab_ids))
        return thread

    def cancel(self) -> None:
        with self._lock:
            runner = self._runner
        if runner is not None:
            runner.cancel()
            self.log.info("Запрошена отмена копирования")

    # ------------------------------------------------------------- внутреннее
    def _run_backup(self, runner: BackupRunner, scheduled: bool, tab_ids: Tuple[str, ...]) -> None:
        try:
            result = runner.run()
        except Exception as error:  # защитный код: поток не должен умереть молча
            self.log.exception("Критическая ошибка копирования")
            result = BackupResult(status=STATUS_FAILED, message=f"Критическая ошибка: {error}",
                                  errors=[str(error)])
        with self._lock:
            self._runner, self._run_thread, self._run_tabs = None, None, ()
            if result.status in (STATUS_OK, STATUS_PARTIAL):
                finished_at = self._now().replace(microsecond=0)
                for tab in self._config.tabs:
                    if tab.uid in tab_ids:
                        tab.last_backup_time = finished_at
            self._save()
        self._log_result(result)
        if not (self._stop.is_set() and result.status == STATUS_CANCELLED):  # иначе запись сделает shutdown
            self._record(f"{RESULT_ICONS.get(result.status, ICON_ERROR)} {result.message}",
                         result.errors + result.over_limit, tab_ids)
        self._emit(BackupFinished(result, scheduled, tab_ids))
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

    def _record(self, text: str, details: Sequence[str] = (), tab_ids: Sequence[str] = ()) -> None:
        """Запись в историю копирования. Окно получает ее событием HistoryAdded."""
        entry = HistoryEntry(self._now().replace(second=0, microsecond=0), text, limit_details(details),
                             tuple(tab_ids))
        try:
            self._history.add(entry)
        except OSError as error:
            self.log.error(f"Не удалось записать историю копирования: {error}")
        self._emit(HistoryAdded(entry))

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
            due = list(self._next_runs.values())
            if self._missed_run_due is not None:
                due.append(self._missed_run_due)
        wait = self._check_interval
        for moment in due:
            wait = min(wait, max(0.2, (moment - now).total_seconds()))
        return wait

    def _schedule_event(self) -> ScheduleChanged:
        """Снимок работающего расписания вкладок, в порядке вкладок. Вызывается под блокировкой."""
        return ScheduleChanged(tuple((tab.uid, self._next_runs[tab.uid])
                                     for tab in self._config.tabs if tab.uid in self._next_runs))

    def _sync_autostart(self) -> list:
        try:
            actual = bool(self._autostart.is_enabled())
        except Exception as error:
            self.log.warning(f"Не удалось проверить автозапуск: {error}")
            return [AppProblem("Не удалось проверить автозапуск", str(error))]
        with self._lock:
            if actual == self._config.auto_start:
                return []
            self._config.auto_start = actual
            self._save()
            config = copy.deepcopy(self._config)
        self.log.info("Состояние автозапуска в системе отличалось от настроек, синхронизировано")
        return [ConfigChanged(config)]

    def _resume_schedule(self) -> bool:
        """Возобновляет расписание вкладок после запуска и планирует пропущенное копирование.

        True, если расписание вкладок изменилось: тогда вызывающий сообщает о нем.
        """
        records: List[Record] = []
        messages: List[Tuple[int, str]] = []
        with self._lock:
            waiting = [tab for tab in self._config.tabs if tab.schedule_on and tab.uid not in self._next_runs]
            if not waiting:
                return False
            now = self._now()
            for tab in waiting:
                self._resume_tab(tab, now, records, messages)
            if self._missed_tabs:
                self._missed_run_due = now + timedelta(seconds=self._missed_run_delay)
            self._save()
        for level, text in messages:
            self.log.log(level, text)
        for text, ids in records:
            self._record(text, tab_ids=ids)
        return True

    def _resume_tab(self, tab: TabConfig, now: datetime, records: List[Record],
                    messages: List[Tuple[int, str]]) -> None:
        """Возобновляет расписание одной вкладки. Вызывается под блокировкой."""
        problems = tab.problems()
        if problems:
            tab.schedule_on = False
            reason = "; ".join(problems)
            messages.append((logging.WARNING, f"Расписание не возобновлено ({tab.title}): {reason}"))
            records.append((f"{ICON_ERROR} Расписание не возобновлено ({tab.title}): {reason}", (tab.uid,)))
            return
        self._next_runs[tab.uid] = upcoming = next_run(tab.schedule(), now)
        messages.append((logging.INFO, f"Расписание возобновлено ({tab.title}), следующее копирование: "
                                       f"{format_run_time(upcoming)}"))
        missed_at = self._missed_run_time(tab, now) if self._config.run_missed else None
        if missed_at is None:
            return
        self._missed_tabs.append(tab.uid)
        messages.append((logging.INFO, f"Назначенное время было пропущено ({tab.title}), "
                                       "копирование будет выполнено сейчас"))
        records.append((f"{ICON_WARNING} Пропущено плановое копирование {missed_at.strftime(TIME_FORMAT)}, "
                        f"выполняется сейчас ({tab.title})", (tab.uid,)))

    @staticmethod
    def _missed_run_time(tab: TabConfig, now: datetime) -> Optional[datetime]:
        """Время пропущенного планового копирования вкладки или None, если пропуска не было."""
        previous = previous_run(tab.schedule(), now)
        marks = [mark for mark in (tab.last_backup_time, tab.timer_started_at) if mark]
        return previous if marks and max(marks) < previous else None

    def _normalize(self) -> None:
        config = self._config
        if not config.tabs:
            config.tabs = [TabConfig()]
        used = set()
        for tab in config.tabs:
            while not tab.uid or tab.uid in used:
                tab.uid = new_tab_uid()
            used.add(tab.uid)
        if not 0 <= config.active_tab < len(config.tabs):
            config.active_tab = 0
        config.max_file_size_gb = max(0, int(config.max_file_size_gb))

    def _save(self) -> None:
        try:
            self._store.save(self._config)
        except OSError as error:
            self._settings_not_saved(error)
            return
        self._settings_write_failed = False

    def _settings_not_saved(self, error: OSError) -> None:
        """Сбой записи настроек: в журнал каждый раз, на экран один раз до следующей удачной записи."""
        self.log.error(f"Не удалось сохранить настройки: {error}")
        if not self._settings_write_failed:
            self._settings_write_failed = True
            # Сохранение идет под блокировкой: событие уйдет при ближайшем _emit вне ее.
            self._pending_events.append(AppProblem("Не удалось сохранить настройки",
                                                   f"Файл {self._store.path} недоступен для записи: {error}"))

    def _policy(self) -> safety.SafetyPolicy:
        return safety.SafetyPolicy(max_file_size=max(0, self._config.max_file_size_gb) * safety.GB,
                                   protected_paths=self._protected.paths)


def _job_from(tab: TabConfig) -> BackupJob:
    return BackupJob(name=tab.title, folders=list(tab.folders), files=list(tab.files),
                     destination=tab.destination, options=tab.options())
