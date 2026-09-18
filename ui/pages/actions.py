#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/pages/actions.py — избор на задачи и пускане на опашка.

Вместо шест отделни бутона (всеки блокиращ останалите), тук се избират
една или няколко задачи с отметки и се пускат ЕДНА СЛЕД ДРУГА с един бутон.
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog

from .. import theme
from ..theme import Fonts
from core import scripts as screg
from core import textutil


class ActionsPage(ttk.Frame):

    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self.vars = {}          # file -> BooleanVar
        self.status_lbls = {}   # file -> Label
        self.rows = {}          # file -> Frame

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ttk.Frame(self, padding=(0, 0, 0, 10))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Действия", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Отметни какво да се изпълни. Задачите се пускат "
                             "една след друга, в реда отдолу.",
                  style="Sub.TLabel").grid(row=1, column=0, sticky="w")

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, uniform="c")
        body.columnconfigure(1, weight=2, uniform="c")
        body.rowconfigure(0, weight=1)

        self._build_task_list(body)
        self._build_side(body)

    # ══════════════════════════════════════════════════════════════════
    def _build_task_list(self, parent):
        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        canvas = tk.Canvas(wrap, bg=theme.BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        inner.columnconfigure(0, weight=1)

        r = 0
        for group, items in screg.by_group():
            ttk.Label(inner, text=group.upper(), style="Sub.TLabel",
                      font=Fonts.small_bold).grid(row=r, column=0, sticky="w",
                                                  pady=(10 if r else 0, 4))
            r += 1
            for sd in items:
                self._task_row(inner, sd, r)
                r += 1

    def _task_row(self, parent, sd, row):
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        card.columnconfigure(1, weight=1)

        var = tk.BooleanVar(value=False)
        self.vars[sd.file] = var
        ttk.Checkbutton(card, variable=var, style="Card.TCheckbutton",
                        command=self._update_summary
                        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))

        top = ttk.Frame(card, style="Card.TFrame")
        top.grid(row=0, column=1, sticky="ew")
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text=sd.label, style="CardBold.TLabel").grid(row=0, column=0, sticky="w")

        badges = ttk.Frame(top, style="Card.TFrame")
        badges.grid(row=0, column=1, sticky="e")
        if sd.writes:
            ttk.Label(badges, text="променя Shopify", style="CardWarn.TLabel").pack(side="left", padx=(6, 0))
        if sd.minutes:
            ttk.Label(badges, text=f"~{sd.minutes} мин", style="CardMuted.TLabel").pack(side="left", padx=(8, 0))
        lbl = ttk.Label(badges, text="", style="CardOk.TLabel")
        lbl.pack(side="left", padx=(8, 0))
        self.status_lbls[sd.file] = lbl

        ttk.Label(card, text=sd.desc, style="CardMuted.TLabel",
                  wraplength=430, justify="left").grid(row=1, column=1, sticky="w", pady=(3, 0))

        self.rows[sd.file] = card

    # ══════════════════════════════════════════════════════════════════
    def _build_side(self, parent):
        side = ttk.Frame(parent)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)

        # ── Режим ──
        mode = ttk.LabelFrame(side, text="Режим", padding=14)
        mode.grid(row=0, column=0, sticky="ew")
        mode.columnconfigure(0, weight=1)

        ttk.Checkbutton(mode, text="ТЕСТ (DRY RUN) — нищо не се променя",
                        style="Card.TCheckbutton", variable=self.app.dry_run,
                        command=self.app.on_mode_change
                        ).grid(row=0, column=0, sticky="w")
        ttk.Label(mode, text="Изключено = реалните промени се записват в Shopify.",
                  style="CardMuted.TLabel", wraplength=300, justify="left"
                  ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        # ── Партиди ──
        batch = ttk.LabelFrame(side, text="Партида (за качване на нови продукти)", padding=14)
        batch.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        batch.columnconfigure(1, weight=1)

        ttk.Label(batch, text="Продукти в партида:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(batch, textvariable=self.app.batch_size, width=8).grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(batch, text="Коя партида:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(batch, textvariable=self.app.batch_number, width=8).grid(row=1, column=1, sticky="w", pady=3)

        # ── Папка ──
        folder = ttk.LabelFrame(side, text="Папка със скриптовете", padding=14)
        folder.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        folder.columnconfigure(0, weight=1)
        ttk.Entry(folder, textvariable=self.app.scripts_dir).grid(row=0, column=0, sticky="ew")
        ttk.Button(folder, text="Избери…", style="Secondary.TButton",
                   command=self._choose_dir).grid(row=0, column=1, padx=(8, 0))
        self.dir_note = ttk.Label(folder, text="", style="CardMuted.TLabel",
                                  wraplength=300, justify="left")
        self.dir_note.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ── Старт ──
        run = ttk.Frame(side)
        run.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run.columnconfigure(0, weight=1)

        self.summary = ttk.Label(run, text="Няма избрани задачи.", style="Sub.TLabel",
                                 wraplength=300, justify="left")
        self.summary.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.start_btn = ttk.Button(run, text="▶  Пусни избраните",
                                    style="Accent.TButton", command=self.app.start_queue)
        self.start_btn.grid(row=1, column=0, sticky="ew")

        sel = ttk.Frame(run)
        sel.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        sel.columnconfigure((0, 1), weight=1)
        ttk.Button(sel, text="Избери всички", style="Secondary.TButton",
                   command=lambda: self._select_all(True)).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(sel, text="Изчисти избора", style="Secondary.TButton",
                   command=lambda: self._select_all(False)).grid(row=0, column=1, sticky="ew", padx=(4, 0))

    # ══════════════════════════════════════════════════════════════════
    def _choose_dir(self):
        path = filedialog.askdirectory(
            title="Избери папката с .py скриптовете",
            initialdir=self.app.scripts_dir.get() or os.getcwd())
        if path:
            self.app.scripts_dir.set(path)

    def _select_all(self, value):
        for sd in screg.SCRIPTS:
            if value and not self.app.present.get(sd.file, False):
                continue
            self.vars[sd.file].set(value)
        self._update_summary()

    def selected(self):
        """Върнатите скриптове са в реда от регистъра."""
        return [sd for sd in screg.SCRIPTS
                if self.vars[sd.file].get() and self.app.present.get(sd.file, False)]

    # ── обновяване след смяна на папка / режим ────────────────────────
    def refresh_availability(self):
        missing_runtime = not self.app.runtime_ok
        for sd in screg.SCRIPTS:
            present = self.app.present.get(sd.file, False)
            lbl = self.status_lbls[sd.file]
            if present:
                lbl.config(text="", style="CardOk.TLabel")
            else:
                lbl.config(text="● липсва файлът", style="CardErr.TLabel")
                self.vars[sd.file].set(False)
        if missing_runtime:
            self.dir_note.config(
                text="ВНИМАНИЕ: runtime.py липсва в тази папка. Без него нито "
                     "един скрипт няма да тръгне.", style="CardErr.TLabel")
        else:
            self.dir_note.config(text="", style="CardMuted.TLabel")
        self._update_summary()

    def _update_summary(self):
        sel = self.selected()
        if not sel:
            self.summary.config(text="Няма избрани задачи.")
            self.start_btn.config(state="disabled")
            return
        mins = sum(s.minutes for s in sel)
        writes = [s for s in sel if s.writes]
        parts = [textutil.tasks(len(sel)), f"~{mins} мин общо"]
        text = " · ".join(parts)
        if writes and not self.app.dry_run.get():
            n = len(writes)
            text += ("\nРЕАЛЕН режим: " +
                     (f"тази задача променя Shopify." if n == 1
                      else f"{n} от тях променят Shopify."))
        self.summary.config(text=text)
        self.start_btn.config(state="normal" if self.app.runtime_ok else "disabled")

    def set_running(self, running):
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        if not running:
            self._update_summary()
