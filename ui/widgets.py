#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/widgets.py — многократно използвани елементи.

LogView       — лог с цветове по вид на реда, филтър „само грешки" и търсене.
ProgressPanel — лента за прогрес с проценти, брояч и оставащо време.
"""

import re
import tkinter as tk
from tkinter import ttk

from . import theme
from .theme import Fonts
from core import textutil


# ── класификация на редовете ──────────────────────────────────────────
_ERR = re.compile(r"ГРЕШКА|ERROR|СПИРАМ|Traceback|!!!!|неуспеш", re.I)
_WARN = re.compile(r"ВНИМАНИЕ|ПРЕДУПРЕЖДЕНИЕ|retry|изчаквам|пропуснат", re.I)
_OK = re.compile(r"Логин OK|Токен OK|Токен получен|Готово|✓|приключи с код 0|"
                 r"РЕЖИМ: ТЕСТ|успешн", re.I)
_HEAD = re.compile(r"^\s*(===|═══|───|\[СТАРТ\]|\[КРАЙ\]|---)")


def classify(line):
    if _ERR.search(line):
        return "err"
    if _WARN.search(line):
        return "warn"
    if _HEAD.search(line):
        return "head"
    if _OK.search(line):
        return "ok"
    return "normal"


class LogView(ttk.Frame):
    """Цветен лог с филтър и търсене. Пази всички редове, за да може
    да превключва между „всичко" и „само грешки" без загуба."""

    def __init__(self, master, height=14, **kw):
        super().__init__(master, **kw)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._lines = []                 # [(вид, текст)] — пълната история
        self.only_errors = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()

        # ── лента с инструменти ──
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.columnconfigure(2, weight=1)

        ttk.Checkbutton(bar, text="Само грешки", variable=self.only_errors,
                        command=self._rerender).grid(row=0, column=0, sticky="w")

        ttk.Label(bar, text="Търси:", style="Sub.TLabel").grid(row=0, column=1, padx=(14, 4))
        ent = ttk.Entry(bar, textvariable=self.search_var, width=24)
        ent.grid(row=0, column=2, sticky="w")
        ent.bind("<Return>", lambda e: self.find_next())
        ttk.Button(bar, text="Намери", style="Secondary.TButton",
                   command=self.find_next).grid(row=0, column=3, padx=(6, 0))

        self.count_lbl = ttk.Label(bar, text="", style="Sub.TLabel")
        self.count_lbl.grid(row=0, column=4, padx=(14, 0), sticky="e")

        # ── самият текст ──
        wrap = ttk.Frame(self)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        self.text = tk.Text(wrap, wrap="word", height=height, state="disabled",
                            font=(Fonts.mono, 10), relief="flat", borderwidth=0,
                            background=theme.LOG_BG, foreground=theme.LOG_FG,
                            insertbackground=theme.LOG_FG, padx=10, pady=8)
        self.text.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=sb.set)

        self.text.tag_configure("err", foreground=theme.LOG_ERR)
        self.text.tag_configure("warn", foreground=theme.LOG_WARN)
        self.text.tag_configure("ok", foreground=theme.LOG_OK)
        self.text.tag_configure("head", foreground=theme.LOG_HEAD,
                                font=(Fonts.mono, 10, "bold"))
        self.text.tag_configure("normal", foreground=theme.LOG_FG)
        self.text.tag_configure("found", background="#3b4a63")

        self._search_pos = "1.0"

    # ── добавяне ──────────────────────────────────────────────────────
    def append(self, line, kind=None):
        kind = kind or classify(line)
        self._lines.append((kind, line))
        if self.only_errors.get() and kind not in ("err", "warn"):
            self._update_count()
            return
        self._write(kind, line)
        self._update_count()

    def _write(self, kind, line):
        at_end = self.text.yview()[1] > 0.98      # авто-скрол само ако си най-долу
        self.text.config(state="normal")
        self.text.insert("end", line, kind)
        self.text.config(state="disabled")
        if at_end:
            self.text.see("end")

    def _rerender(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        only = self.only_errors.get()
        for kind, line in self._lines:
            if only and kind not in ("err", "warn"):
                continue
            self._write(kind, line)
        self._update_count()

    def _update_count(self):
        errs = sum(1 for k, _ in self._lines if k == "err")
        warns = sum(1 for k, _ in self._lines if k == "warn")
        parts = []
        if errs:
            parts.append(textutil.errors(errs))
        if warns:
            parts.append(textutil.warnings(warns))
        self.count_lbl.config(text=" · ".join(parts) if parts else "")

    # ── търсене ───────────────────────────────────────────────────────
    def find_next(self):
        term = self.search_var.get().strip()
        self.text.tag_remove("found", "1.0", "end")
        if not term:
            return
        pos = self.text.search(term, self._search_pos, nocase=True, stopindex="end")
        if not pos:
            pos = self.text.search(term, "1.0", nocase=True, stopindex="end")
            if not pos:
                return
        end = f"{pos}+{len(term)}c"
        self.text.tag_add("found", pos, end)
        self.text.see(pos)
        self._search_pos = end

    # ── останало ──────────────────────────────────────────────────────
    def clear(self):
        self._lines.clear()
        self._search_pos = "1.0"
        self._rerender()

    def get_all(self):
        return "".join(line for _, line in self._lines)


class ProgressPanel(ttk.Frame):
    """Лента за прогрес + текст „340 / 1200 · остават ~12 мин"."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.columnconfigure(0, weight=1)

        self.caption = ttk.Label(self, text="Готово за работа.", style="Sub.TLabel")
        self.caption.grid(row=0, column=0, sticky="w")

        self.detail = ttk.Label(self, text="", style="Sub.TLabel")
        self.detail.grid(row=0, column=1, sticky="e")

        self.bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def idle(self, text="Готово за работа."):
        self.bar.stop()
        self.bar.config(mode="determinate", maximum=100, value=0)
        self.caption.config(text=text)
        self.detail.config(text="")

    def indeterminate(self, text):
        """Задачата върви, но още не знаем колко общо."""
        self.caption.config(text=text)
        self.detail.config(text="")
        self.bar.config(mode="indeterminate")
        self.bar.start(12)

    def set_progress(self, text, done, total, eta_text=""):
        self.bar.stop()
        self.bar.config(mode="determinate", maximum=max(total, 1), value=done)
        self.caption.config(text=text)
        pct = done / total * 100 if total else 0
        d = f"{done} / {total}  ·  {pct:.0f}%"
        if eta_text:
            d += f"  ·  остават ~{eta_text}"
        self.detail.config(text=d)
