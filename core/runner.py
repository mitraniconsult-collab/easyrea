#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runner.py — изпълнява ОПАШКА от задачи една след друга.

Как работи:
  • Всяка задача е отделен процес (python скрипт.py …).
  • Работна нишка чете stdout ред по ред и бута събития в опашка.
  • Интерфейсът чете събитията от главната нишка (безопасно за tkinter).

Разпознава редовете „PROGRESS i/n", които скриптовете печатат, и от тях
смята процент и оставащо време. Тези редове НЕ влизат в лога — те се
показват в лентата за прогрес.

Събития (кортежи в self.events):
    ("QUEUE_START", брой_задачи)
    ("TASK_START",  индекс)
    ("LOG",         индекс, ред)
    ("PROGRESS",    индекс, i, n, секунди_остават_или_None)
    ("TASK_DONE",   индекс, код_на_изход)
    ("QUEUE_DONE",  обобщение_dict)
"""

import os
import re
import sys
import collections
import time
import queue
import signal
import threading
import subprocess


PROGRESS_RE = re.compile(r"^\s*PROGRESS\s+(\d+)\s*/\s*(\d+)\s*$")

# Статуси на задача
WAITING = "waiting"
RUNNING = "running"
DONE = "done"
ERROR = "error"
STOPPED = "stopped"
SKIPPED = "skipped"

STATUS_TEXT = {
    WAITING: "чака",
    RUNNING: "изпълнява се",
    DONE: "готово",
    ERROR: "грешка",
    STOPPED: "спряно",
    SKIPPED: "пропуснато",
}


class Task:
    """Една задача в опашката."""

    def __init__(self, script, args=None, env_extra=None):
        self.script = script            # ScriptDef
        self.args = list(args or [])
        self.env_extra = dict(env_extra or {})
        self.status = WAITING
        self.rc = None
        self.done = 0
        self.total = 0
        self.started_at = None
        self.finished_at = None
        self.log_path = None
        self.error_count = 0
        # последните редове — от тях се вади блокът „ОБОБЩЕНИЕ" за историята
        self.tail = collections.deque(maxlen=400)
        self.summary = {}

    @property
    def label(self):
        return self.script.label

    @property
    def percent(self):
        if not self.total:
            return None
        return min(100.0, self.done / self.total * 100.0)

    @property
    def elapsed(self):
        if not self.started_at:
            return 0
        end = self.finished_at or time.time()
        return end - self.started_at


class QueueRunner:
    """
    Пуска списък от Task-ове последователно. Не блокира интерфейса.
    Всичко от работната нишка идва през self.events.
    """

    def __init__(self):
        self.events = queue.Queue()
        self.tasks = []
        self.scripts_dir = ""
        self.env = {}
        self._proc = None
        self._thread = None
        self._stop_all = False
        self._stop_current = False
        self._lock = threading.Lock()

    # ── състояние ─────────────────────────────────────────────────────
    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    # ── стартиране ────────────────────────────────────────────────────
    def start(self, tasks, scripts_dir, env, log_dir=None):
        if self.busy:
            raise RuntimeError("Вече се изпълнява опашка.")
        self.tasks = list(tasks)
        self.scripts_dir = scripts_dir
        self.env = dict(env)
        self.log_dir = log_dir
        self._stop_all = False
        self._stop_current = False
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # ── спиране ───────────────────────────────────────────────────────
    def stop_current(self):
        """Спира текущата задача, но продължава със следващите."""
        self._stop_current = True
        self._kill()

    def stop_all(self):
        """Спира текущата задача и отменя останалите."""
        self._stop_all = True
        self._kill()

    def _kill(self):
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError, ValueError):
            try:
                proc.terminate()
            except OSError:
                pass

    # ── работната нишка ───────────────────────────────────────────────
    def _worker(self):
        self.events.put(("QUEUE_START", len(self.tasks)))
        summary = {"done": 0, "error": 0, "stopped": 0, "skipped": 0}

        for idx, task in enumerate(self.tasks):
            if self._stop_all:
                task.status = SKIPPED
                summary["skipped"] += 1
                self.events.put(("TASK_DONE", idx, None))
                continue

            self._stop_current = False
            task.status = RUNNING
            task.started_at = time.time()
            self.events.put(("TASK_START", idx))

            rc = self._run_one(idx, task)

            task.rc = rc
            task.finished_at = time.time()
            if self._stop_current or self._stop_all:
                task.status = STOPPED
                summary["stopped"] += 1
            elif rc == 0:
                task.status = DONE
                summary["done"] += 1
            else:
                task.status = ERROR
                summary["error"] += 1

            self.events.put(("TASK_DONE", idx, rc))

        self.events.put(("QUEUE_DONE", summary))

    def _run_one(self, idx, task):
        path = os.path.join(self.scripts_dir, task.script.file)
        if not os.path.isfile(path):
            self.events.put(("LOG", idx, f"[ГРЕШКА] Липсва файлът: {path}\n"))
            return 127

        env = os.environ.copy()
        env.update(self.env)
        env.update(task.env_extra)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        cmd = [sys.executable, "-u", path] + task.args

        kwargs = dict(
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=self.scripts_dir, env=env, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
        )
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(cmd, **kwargs)
        except OSError as e:
            self.events.put(("LOG", idx, f"[ГРЕШКА] Неуспешно стартиране: {e}\n"))
            return 126

        with self._lock:
            self._proc = proc

        logfile = None
        if self.log_dir:
            try:
                os.makedirs(self.log_dir, exist_ok=True)
                name = f"{time.strftime('%Y%m%d_%H%M%S')}_{task.script.file}.log"
                task.log_path = os.path.join(self.log_dir, name)
                logfile = open(task.log_path, "w", encoding="utf-8")
            except OSError:
                logfile = None
                task.log_path = None

        try:
            for line in iter(proc.stdout.readline, ""):
                if logfile:
                    logfile.write(line)

                m = PROGRESS_RE.match(line)
                if m:
                    task.done, task.total = int(m.group(1)), int(m.group(2))
                    self.events.put(("PROGRESS", idx, task.done, task.total,
                                     self._eta(task)))
                    continue        # PROGRESS редовете не отиват в лога

                task.tail.append(line)
                if "ГРЕШКА" in line or "ERROR" in line or "СПИРАМ" in line:
                    task.error_count += 1
                self.events.put(("LOG", idx, line))
        except Exception as e:                                   # noqa: BLE001
            self.events.put(("LOG", idx, f"[ГРЕШКА при четене] {e}\n"))
        finally:
            if logfile:
                try:
                    logfile.close()
                except OSError:
                    pass
            try:
                proc.stdout.close()
            except OSError:
                pass

        rc = proc.wait()
        with self._lock:
            self._proc = None

        # изваждаме числата от финалното обобщение
        try:
            from . import summary as summary_mod
            task.summary = summary_mod.parse(list(task.tail))
        except Exception:                                        # noqa: BLE001
            task.summary = {}

        return rc

    @staticmethod
    def _eta(task):
        """Оставащо време в секунди по средното темпо досега."""
        if not task.total or not task.done or not task.started_at:
            return None
        elapsed = time.time() - task.started_at
        if elapsed < 3 or task.done >= task.total:
            return None
        per_item = elapsed / task.done
        return max(0, (task.total - task.done) * per_item)


# ── помощно форматиране ───────────────────────────────────────────────
def fmt_duration(seconds):
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} сек"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} мин {s:02d} сек"
    h, m = divmod(m, 60)
    return f"{h} ч {m:02d} мин"
