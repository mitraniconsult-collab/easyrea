#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/pages/run.py — екранът „Изпълнение".

Показва:
  • списъка със задачите в опашката и статуса на всяка;
  • лента за прогрес с брояч и оставащо време за текущата;
  • цветния лог в реално време.
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

from .. import theme
from ..widgets import LogView, ProgressPanel
from core.runner import STATUS_TEXT, RUNNING, DONE, ERROR, STOPPED, WAITING, SKIPPED
from core.runner import fmt_duration
from core import textutil


_STYLE_FOR = {
    WAITING: ("CardMuted.TLabel", "чака"),
    RUNNING: ("CardWarn.TLabel", "изпълнява се…"),
    DONE:    ("CardOk.TLabel", "готово"),
    ERROR:   ("CardErr.TLabel", "грешка"),
    STOPPED: ("CardErr.TLabel", "спряно"),
    SKIPPED: ("CardMuted.TLabel", "пропуснато"),
}


class RunPage(ttk.Frame):

    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self.task_rows = []

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        head = ttk.Frame(self, padding=(0, 0, 0, 10))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Изпълнение", style="Title.TLabel").grid(row=0, column=0, sticky="w")

        # ── опашка ──
        self.queue_frame = ttk.LabelFrame(self, text="Опашка", padding=12)
        self.queue_frame.grid(row=1, column=0, sticky="ew")
        self.queue_frame.columnconfigure(0, weight=1)
        self.empty_lbl = ttk.Label(self.queue_frame,
                                   text="Няма пусната опашка. Отиди в раздел "
                                        "„Действия“, избери задачи и натисни "
                                        "„Пусни избраните“.",
                                   style="CardMuted.TLabel")
        self.empty_lbl.grid(row=0, column=0, sticky="w")

        # ── прогрес + бутони за спиране ──
        ctrl = ttk.Frame(self, padding=(0, 12, 0, 8))
        ctrl.grid(row=2, column=0, sticky="ew")
        ctrl.columnconfigure(0, weight=1)

        self.progress = ProgressPanel(ctrl)
        self.progress.grid(row=0, column=0, sticky="ew")

        btns = ttk.Frame(ctrl)
        btns.grid(row=0, column=1, sticky="e", padx=(14, 0))
        self.skip_btn = ttk.Button(btns, text="Пропусни текущата",
                                   style="Secondary.TButton",
                                   command=self._skip, state="disabled")
        self.skip_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(btns, text="⏹  Спри всичко",
                                   style="Danger.TButton",
                                   command=self._stop, state="disabled")
        self.stop_btn.pack(side="left")

        # ── лог ──
        logframe = ttk.LabelFrame(self, text="Лог", padding=10)
        logframe.grid(row=3, column=0, sticky="nsew")
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)

        self.log = LogView(logframe, height=14)
        self.log.grid(row=0, column=0, sticky="nsew")

        logbtns = ttk.Frame(logframe)
        logbtns.grid(row=1, column=0, sticky="e", pady=(8, 0))
        ttk.Button(logbtns, text="Изчисти", style="Secondary.TButton",
                   command=self.log.clear).pack(side="left", padx=4)
        ttk.Button(logbtns, text="Запази във файл…", style="Secondary.TButton",
                   command=self._save_log).pack(side="left", padx=4)
        self.autosave_lbl = ttk.Label(logbtns, text="", style="Sub.TLabel")
        self.autosave_lbl.pack(side="left", padx=(10, 0))

    # ══════════════════════════════════════════════════════════════════
    #  Опашка
    # ══════════════════════════════════════════════════════════════════
    def build_queue(self, tasks):
        for w in self.queue_frame.winfo_children():
            w.destroy()
        self.task_rows = []

        for i, t in enumerate(tasks):
            row = ttk.Frame(self.queue_frame, style="Card.TFrame")
            row.grid(row=i, column=0, sticky="ew", pady=2)
            row.columnconfigure(1, weight=1)

            num = ttk.Label(row, text=f"{i + 1}.", style="CardMuted.TLabel", width=3)
            num.grid(row=0, column=0, sticky="w")
            name = ttk.Label(row, text=t.label, style="Card.TLabel")
            name.grid(row=0, column=1, sticky="w")
            timing = ttk.Label(row, text="", style="CardMuted.TLabel")
            timing.grid(row=0, column=2, sticky="e", padx=(10, 10))
            status = ttk.Label(row, text="чака", style="CardMuted.TLabel")
            status.grid(row=0, column=3, sticky="e")

            self.task_rows.append({"name": name, "status": status, "timing": timing})

        self.update_task(0, tasks[0]) if tasks else None

    def update_task(self, idx, task):
        if idx >= len(self.task_rows):
            return
        style, text = _STYLE_FOR.get(task.status, ("CardMuted.TLabel", task.status))
        row = self.task_rows[idx]
        row["status"].config(text=text, style=style)
        if task.status == RUNNING:
            row["name"].config(style="CardBold.TLabel")
        else:
            row["name"].config(style="Card.TLabel")
        if task.finished_at:
            extra = f"{fmt_duration(task.elapsed)}"
            if task.error_count:
                extra += f" · {textutil.errors(task.error_count)}"
            row["timing"].config(text=extra)

    # ══════════════════════════════════════════════════════════════════
    #  Прогрес и лог
    # ══════════════════════════════════════════════════════════════════
    def task_started(self, task, idx, total):
        self.progress.indeterminate(f"[{idx + 1}/{total}] {task.label} — стартира…")
        self.skip_btn.config(state="normal" if total > 1 else "disabled")
        self.stop_btn.config(state="normal")
        if task.log_path:
            self.autosave_lbl.config(text="лог се записва автоматично")

    def task_progress(self, task, idx, total, done, n, eta):
        self.progress.set_progress(
            f"[{idx + 1}/{total}] {task.label}", done, n,
            fmt_duration(eta) if eta else "")

    def queue_finished(self, summary):
        self.skip_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        bits = []
        if summary["done"]:
            n = summary["done"]
            bits.append(f"{n} " + ("успешна" if n == 1 else "успешни"))
        if summary["error"]:
            bits.append(f"{summary['error']} с грешка")
        if summary["stopped"]:
            n = summary["stopped"]
            bits.append(f"{n} " + ("спряна" if n == 1 else "спрени"))
        if summary["skipped"]:
            n = summary["skipped"]
            bits.append(f"{n} " + ("пропусната" if n == 1 else "пропуснати"))
        self.progress.idle("Опашката приключи: " + (", ".join(bits) or "нищо"))

    def append_log(self, line):
        self.log.append(line)

    # ══════════════════════════════════════════════════════════════════
    def _stop(self):
        if messagebox.askyesno("Спиране",
                               "Да спра текущата задача и да отменя останалите?"):
            self.app.runner.stop_all()
            self.append_log("\n[ПРЕКЪСВАНЕ] Спиране на цялата опашка…\n")

    def _skip(self):
        if messagebox.askyesno("Пропускане",
                               "Да спра текущата задача и да продължа със следващата?"):
            self.app.runner.stop_current()
            self.append_log("\n[ПРЕКЪСВАНЕ] Пропускане на текущата задача…\n")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстов файл", "*.txt"), ("Всички файлове", "*.*")],
            initialfile=f"log_{datetime.now():%Y%m%d_%H%M%S}.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log.get_all())
            self.app.set_status(f"Логът е записан: {path}")
        except OSError as e:
            messagebox.showerror("Грешка", f"Неуспешен запис:\n{e}")
