#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/main_window.py — обвивката на приложението.

Съдържа страничната навигация, лентата за режим (ТЕСТ / РЕАЛЕН),
страниците и „помпата", която тегли събитията от опашката в главната
нишка на tkinter.
"""

import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from . import theme
from .theme import Fonts, apply_theme
from .pages.dashboard import DashboardPage
from .pages.actions import ActionsPage
from .pages.run import RunPage
from .pages.reports import ReportsPage
from .pages.settings import SettingsPage

from core import scripts as screg
from core.config import Config, CRED_FIELDS, CRED_KEYS
from core.runner import QueueRunner, Task
from core.history import History
from core import textutil


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
HISTORY_PATH = os.path.join(APP_DIR, "history.db")

NAV = [
    ("dashboard", "Табло"),
    ("actions", "Действия"),
    ("run", "Изпълнение"),
    ("reports", "Отчети"),
    ("settings", "Настройки"),
]


class MainWindow(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("EasyRea ↔ Shopify — Синхронизация")
        self.minsize(1000, 620)

        self.cfg = Config(CONFIG_PATH).load()
        self.history = History(HISTORY_PATH)
        self.runner = QueueRunner()
        self.present = {}
        self.runtime_ok = False
        self._queue_tasks = []
        self._current_idx = None

        # ── Tk променливи ──
        self.cred_vars = {k: tk.StringVar(value=self.cfg.text(k)) for k in CRED_KEYS}
        self.batch_size = tk.StringVar(value=self.cfg.text("BATCH_SIZE", "500"))
        self.batch_number = tk.StringVar(value=self.cfg.text("BATCH_NUMBER", "1"))
        self.scripts_dir = tk.StringVar(value=self.cfg.text("SCRIPTS_DIR") or APP_DIR)
        self.dry_run = tk.BooleanVar(value=self.cfg.flag("DRY_RUN", True))
        self.autosave_logs = tk.BooleanVar(value=self.cfg.flag("AUTOSAVE_LOGS", True))
        self.show_secrets = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="Готово.")

        apply_theme(self)
        self._restore_geometry()
        self._build()

        self.scripts_dir.trace_add("write", lambda *a: self.refresh_scripts())
        self.refresh_scripts()
        self.on_mode_change()

        if self.cfg.load_error:
            self.pages["run"].append_log(
                f"[ВНИМАНИЕ] config.json не се прочете: {self.cfg.load_error}\n")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._pump)

    # ══════════════════════════════════════════════════════════════════
    #  Изграждане
    # ══════════════════════════════════════════════════════════════════
    def _build(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(1, weight=1)

        self.mode_bar = tk.Frame(self, height=6, bg=theme.MODE_TEST)
        self.mode_bar.grid(row=0, column=0, columnspan=2, sticky="ew")

        self._build_sidebar()

        holder = ttk.Frame(self, padding=(20, 16, 20, 8))
        holder.grid(row=1, column=1, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        self.pages = {
            "dashboard": DashboardPage(holder, self),
            "actions": ActionsPage(holder, self),
            "run": RunPage(holder, self),
            "reports": ReportsPage(holder, self),
            "settings": SettingsPage(holder, self),
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")

        bar = ttk.Frame(self, padding=(20, 4, 20, 10))
        bar.grid(row=2, column=1, sticky="ew")
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status_text, style="Status.TLabel"
                  ).grid(row=0, column=0, sticky="w")
        self.mode_lbl = ttk.Label(bar, text="", style="Status.TLabel")
        self.mode_lbl.grid(row=0, column=1, sticky="e")

        self.show_page("dashboard")

    def _build_sidebar(self):
        side = tk.Frame(self, bg=theme.SIDEBAR, width=190)
        side.grid(row=1, column=0, rowspan=2, sticky="nsw")
        side.grid_propagate(False)

        tk.Label(side, text="EasyRea ↔ Shopify", bg=theme.SIDEBAR, fg="white",
                 font=(Fonts.family, 12, "bold"), anchor="w", padx=16, pady=6
                 ).pack(fill="x", pady=(18, 0))
        tk.Label(side, text="управление на синхронизацията", bg=theme.SIDEBAR,
                 fg=theme.SIDEBAR_FG, font=(Fonts.family, 8), anchor="w",
                 padx=16, wraplength=160, justify="left").pack(fill="x", pady=(0, 16))

        self.nav_btns = {}
        for key, label in NAV:
            b = tk.Label(side, text="   " + label, bg=theme.SIDEBAR, fg=theme.SIDEBAR_FG,
                         font=Fonts.nav, anchor="w", padx=14, pady=11, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            b.bind("<Enter>", lambda e, w=b: self._nav_hover(w, True))
            b.bind("<Leave>", lambda e, w=b: self._nav_hover(w, False))
            self.nav_btns[key] = b

        self.queue_badge = tk.Label(side, text="", bg=theme.SIDEBAR,
                                    fg=theme.MODE_REAL, font=(Fonts.family, 9, "bold"),
                                    anchor="w", padx=16, wraplength=160, justify="left")
        self.queue_badge.pack(fill="x", pady=(14, 0))

    def _nav_hover(self, widget, entering):
        if widget.cget("bg") == theme.SIDEBAR_AC:
            return
        widget.config(bg="#2b3646" if entering else theme.SIDEBAR)

    def show_page(self, key):
        for k, b in self.nav_btns.items():
            active = (k == key)
            b.config(bg=theme.SIDEBAR_AC if active else theme.SIDEBAR,
                     fg="white" if active else theme.SIDEBAR_FG)
        page = self.pages[key]
        # Табло и Отчети четат от диска — опресняват се при всяко отваряне
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as e:                               # noqa: BLE001
                self.set_status(f"Грешка при обновяване на „{key}“: {e}")
        page.tkraise()
        self._active_page = key

    # ══════════════════════════════════════════════════════════════════
    #  Режим
    # ══════════════════════════════════════════════════════════════════
    def on_mode_change(self):
        test = self.dry_run.get()
        self.mode_bar.config(bg=theme.MODE_TEST if test else theme.MODE_REAL)
        self.mode_lbl.config(
            text="Режим: ТЕСТ — нищо не се променя" if test
            else "Режим: РЕАЛЕН — промените се записват")
        if "actions" in getattr(self, "pages", {}):
            self.pages["actions"]._update_summary()

    # ══════════════════════════════════════════════════════════════════
    #  Скриптове в папката
    # ══════════════════════════════════════════════════════════════════
    @property
    def dir_now(self):
        return self.scripts_dir.get().strip() or APP_DIR

    @property
    def log_dir(self):
        return os.path.join(self.dir_now, "logs")

    def refresh_scripts(self):
        d = self.dir_now
        for sd in screg.SCRIPTS:
            self.present[sd.file] = os.path.isfile(os.path.join(d, sd.file))
        self.runtime_ok = os.path.isfile(os.path.join(d, "runtime.py"))
        if hasattr(self, "pages"):
            self.pages["actions"].refresh_availability()
        missing = [s.file for s in screg.SCRIPTS if not self.present[s.file]]
        if not self.runtime_ok:
            self.set_status("ВНИМАНИЕ: runtime.py липсва — скриптовете няма да тръгнат.")
        elif missing:
            self.set_status(f"Липсват файлове: {', '.join(missing)}")
        else:
            self.set_status("Всички скриптове са намерени.")

    # ══════════════════════════════════════════════════════════════════
    #  Стартиране на опашка
    # ══════════════════════════════════════════════════════════════════
    def start_queue(self):
        if self.runner.busy:
            messagebox.showwarning("Изчакай", "Вече се изпълнява опашка.")
            return

        selected = self.pages["actions"].selected()
        if not selected:
            messagebox.showinfo("Няма избор", "Отметни поне една задача.")
            return

        if not self._validate_batch(selected):
            return

        missing = [k for k in CRED_KEYS if not self.cred_vars[k].get().strip()]
        if missing:
            if not messagebox.askyesno(
                    "Липсват настройки",
                    "Не са попълнени: " + ", ".join(missing) +
                    "\n\nСкриптовете вероятно ще спрат веднага. Да продължа ли?",
                    icon="warning", default="no"):
                self.show_page("settings")
                return

        # Потвърждение за реален режим
        writes = [s for s in selected if s.writes]
        if writes and not self.dry_run.get():
            names = "\n".join(f"  • {s.label}" for s in writes)
            if not messagebox.askyesno(
                    "Реален режим",
                    "РЕЖИМЪТ Е РЕАЛЕН — промените ще бъдат записани в Shopify.\n\n"
                    f"Задачи, които променят данни:\n{names}\n\nДа продължа ли?",
                    icon="warning", default="no"):
                return

        try:
            self.save_config()
        except OSError:
            pass

        tasks = [Task(sd, args=self._args_for(sd)) for sd in selected]
        self._queue_tasks = tasks
        self._current_idx = None

        self.pages["run"].build_queue(tasks)
        self.pages["run"].append_log(
            "\n" + "═" * 70 + "\n"
            f"[ОПАШКА] {textutil.tasks(len(tasks))} · "
            f"{'ТЕСТ' if self.dry_run.get() else 'РЕАЛЕН режим'} · "
            f"{datetime.now():%Y-%m-%d %H:%M:%S}\n" + "═" * 70 + "\n")
        self.pages["actions"].set_running(True)
        self.show_page("run")

        log_dir = self.log_dir if self.autosave_logs.get() else None
        self.runner.start(tasks, self.dir_now, self._env(), log_dir=log_dir)

    def _validate_batch(self, selected):
        if not any(s.batch for s in selected):
            return True
        for label, var in (("Продукти в партида", self.batch_size),
                           ("Коя партида", self.batch_number)):
            v = var.get().strip()
            if not v.isdigit() or int(v) <= 0:
                messagebox.showerror(
                    "Невалидна стойност",
                    f"„{label}\" трябва да е цяло положително число.")
                self.show_page("actions")
                return False
        return True

    def _env(self):
        env = {k: v.get().strip() for k, v in self.cred_vars.items()}
        env["DRY_RUN"] = "1" if self.dry_run.get() else "0"
        env["BATCH_SIZE"] = self.batch_size.get().strip()
        env["BATCH_NUMBER"] = self.batch_number.get().strip()
        return env

    def _args_for(self, sd):
        args = []
        if sd.dry_run:
            args.append("--dry-run" if self.dry_run.get() else "--real-run")
        if sd.batch:
            args += ["--batch-size", self.batch_size.get().strip(),
                     "--batch-number", self.batch_number.get().strip()]
        return args

    # ══════════════════════════════════════════════════════════════════
    #  Помпа за събития (главна нишка)
    # ══════════════════════════════════════════════════════════════════
    def _pump(self):
        run = self.pages["run"]
        try:
            while True:
                ev = self.runner.events.get_nowait()
                kind = ev[0]

                if kind == "QUEUE_START":
                    self.set_status(f"Стартира опашка от {textutil.tasks(ev[1])}…")

                elif kind == "TASK_START":
                    idx = ev[1]
                    self._current_idx = idx
                    t = self._queue_tasks[idx]
                    run.update_task(idx, t)
                    run.task_started(t, idx, len(self._queue_tasks))
                    run.append_log(f"\n[СТАРТ] {t.label}  ({t.script.file})  "
                                   f"{datetime.now():%H:%M:%S}\n")
                    self.set_status(f"Изпълнява се: {t.label}")
                    self.queue_badge.config(
                        text=f"▶ {idx + 1}/{len(self._queue_tasks)}\n{t.label}")

                elif kind == "LOG":
                    run.append_log(ev[2])

                elif kind == "PROGRESS":
                    _, idx, done, n, eta = ev
                    run.task_progress(self._queue_tasks[idx], idx,
                                      len(self._queue_tasks), done, n, eta)

                elif kind == "TASK_DONE":
                    idx, rc = ev[1], ev[2]
                    t = self._queue_tasks[idx]
                    run.update_task(idx, t)
                    if rc is not None:
                        self.history.record(t, self.dry_run.get())
                        run.append_log(
                            f"[КРАЙ] {t.label} — код {rc}"
                            f"{' (успешно)' if rc == 0 else ''}  "
                            f"{datetime.now():%H:%M:%S}\n")

                elif kind == "QUEUE_DONE":
                    self._on_queue_done(ev[1])

        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _on_queue_done(self, summary):
        self.pages["run"].queue_finished(summary)
        self.pages["actions"].set_running(False)
        self.queue_badge.config(text="")
        self._current_idx = None
        for key in ("dashboard", "reports"):
            try:
                self.pages[key].refresh()
            except Exception:                                    # noqa: BLE001
                pass
        n = summary["done"]
        bits = [f"{n} " + ("успешна" if n == 1 else "успешни")]
        if summary["error"]:
            bits.append(f"{summary['error']} с грешка")
        if summary["stopped"] or summary["skipped"]:
            bits.append(f"{summary['stopped'] + summary['skipped']} спрени/пропуснати")
        self.set_status("Опашката приключи: " + ", ".join(bits))

    # ══════════════════════════════════════════════════════════════════
    #  Настройки и затваряне
    # ══════════════════════════════════════════════════════════════════
    def set_status(self, text):
        self.status_text.set(text)

    def save_config(self):
        for k, v in self.cred_vars.items():
            self.cfg[k] = v.get()
        self.cfg["BATCH_SIZE"] = self.batch_size.get()
        self.cfg["BATCH_NUMBER"] = self.batch_number.get()
        self.cfg["SCRIPTS_DIR"] = self.scripts_dir.get()
        self.cfg["DRY_RUN"] = bool(self.dry_run.get())
        self.cfg["AUTOSAVE_LOGS"] = bool(self.autosave_logs.get())
        self.cfg["WINDOW"] = self.geometry()
        self.cfg.save()

    def _restore_geometry(self):
        geo = self.cfg.text("WINDOW")
        if geo:
            try:
                self.geometry(geo)
                return
            except tk.TclError:
                pass
        self.geometry("1180x760")

    def _on_close(self):
        if self.runner.busy:
            if not messagebox.askyesno(
                    "Изход", "Изпълнява се опашка. Да я спра и да затворя?"):
                return
            self.runner.stop_all()
        try:
            self.save_config()
        except OSError:
            pass
        self.destroy()
