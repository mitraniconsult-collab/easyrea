#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/pages/dashboard.py — началният екран.

Отговаря на въпроса „какво е състоянието в момента":
  • за всяка редовна задача — кога е пусната последно, какво е излязло
    и дали е просрочена;
  • какво изисква внимание днес;
  • последните пускания в таблица.
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime

from .. import theme
from ..theme import Fonts
from core import scripts as screg
from core import history as hist
from core import reports as rep
from core import summary as summ
from core import textutil
from core.runner import fmt_duration


DUE_STYLE = {
    "overdue": ("CardErr.TLabel", "⚠"),
    "never":   ("CardWarn.TLabel", "•"),
    "soon":    ("CardWarn.TLabel", "•"),
    "ok":      ("CardOk.TLabel", "✓"),
    "none":    ("CardMuted.TLabel", ""),
}


class DashboardPage(ttk.Frame):

    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self.cards = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        head = ttk.Frame(self, padding=(0, 0, 0, 10))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Табло", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.subtitle = ttk.Label(head, text="", style="Sub.TLabel")
        self.subtitle.grid(row=1, column=0, sticky="w")
        hbtn = ttk.Frame(head)
        hbtn.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(hbtn, text="Провери връзката", style="Secondary.TButton",
                   command=self._goto_check).pack(side="left", padx=(0, 6))
        ttk.Button(hbtn, text="Обнови", style="Secondary.TButton",
                   command=self.refresh).pack(side="left")

        self._build_cards()
        self._build_attention()
        self._build_recent()

    def _goto_check(self):
        """Отваря Настройки и пуска проверката веднага."""
        self.app.show_page("settings")
        self.app.pages["settings"].run_check()

    # ══════════════════════════════════════════════════════════════════
    def _build_cards(self):
        wrap = ttk.Frame(self)
        wrap.grid(row=1, column=0, sticky="ew")

        tracked = [s for s in screg.SCRIPTS if s.group == screg.GROUP_REGULAR]
        for i in range(len(tracked)):
            wrap.columnconfigure(i, weight=1, uniform="cards")

        for i, sd in enumerate(tracked):
            card = ttk.Frame(wrap, style="Card.TFrame", padding=14)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            card.columnconfigure(0, weight=1)

            title = ttk.Label(card, text=sd.label, style="CardBold.TLabel",
                              wraplength=200, justify="left")
            title.grid(row=0, column=0, sticky="w")

            when = ttk.Label(card, text="—", style="CardMuted.TLabel")
            when.grid(row=1, column=0, sticky="w", pady=(6, 0))

            result = ttk.Label(card, text="", style="Card.TLabel",
                               wraplength=210, justify="left")
            result.grid(row=2, column=0, sticky="w", pady=(6, 0))

            due = ttk.Label(card, text="", style="CardMuted.TLabel")
            due.grid(row=3, column=0, sticky="w", pady=(8, 0))

            self.cards[sd.file] = {"when": when, "result": result, "due": due}

    def _build_attention(self):
        self.attention = ttk.LabelFrame(self, text="Изисква внимание", padding=12)
        self.attention.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.attention.columnconfigure(0, weight=1)

    def _build_recent(self):
        frame = ttk.LabelFrame(self, text="Последни пускания", padding=10)
        frame.grid(row=3, column=0, sticky="nsew", pady=(14, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("when", "task", "mode", "status", "duration", "result")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        for key, text, width, anchor in (
                ("when", "Кога", 130, "w"),
                ("task", "Задача", 210, "w"),
                ("mode", "Режим", 80, "w"),
                ("status", "Резултат", 110, "w"),
                ("duration", "Времетраене", 110, "w"),
                ("result", "Обобщение", 320, "w")):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "result"))
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.tag_configure("err", foreground=theme.DANGER)
        self.tree.tag_configure("test", foreground=theme.MUTED)

        self.empty_note = ttk.Label(frame, text="", style="CardMuted.TLabel")
        self.empty_note.grid(row=1, column=0, sticky="w", pady=(6, 0))

    # ══════════════════════════════════════════════════════════════════
    #  Обновяване
    # ══════════════════════════════════════════════════════════════════
    def refresh(self):
        h = self.app.history
        self.subtitle.config(
            text=f"Състояние към {datetime.now():%d.%m.%Y %H:%M}"
                 + ("" if h.enabled else "  ·  историята не е достъпна"))

        attention = []

        for sd in screg.SCRIPTS:
            if sd.file not in self.cards:
                continue
            last = h.last_for(sd.file)
            # Графикът се брои от последното УСПЕШНО пускане — провалено
            # пускане не значи, че задачата е свършена.
            last_ok = h.last_for(sd.file, successful_only=True)
            c = self.cards[sd.file]

            if not last:
                c["when"].config(text="не е пускана")
                c["result"].config(text="", style="Card.TLabel")
            else:
                mode = "тест" if last.get("dry_run") else "реален"
                c["when"].config(text=f"{hist.ago(last['started_at'])} · {mode}")

                counts = hist.counts_of(last)
                if last.get("rc") == 0:
                    text = summ.human(counts) or "приключи успешно"
                    c["result"].config(text=text, style="Card.TLabel")
                else:
                    c["result"].config(
                        text=f"приключи с грешка (код {last.get('rc')})",
                        style="CardErr.TLabel")
                    attention.append(
                        (f"„{sd.label}\" последно приключи с грешка "
                         f"({hist.ago(last['started_at'])}).", "err"))

                errs = last.get("errors") or 0
                if last.get("rc") == 0 and errs:
                    attention.append(
                        (f"„{sd.label}\" мина, но има {textutil.errors(errs)} в лога.", "warn"))

            state, text = hist.due_state(sd, last_ok)
            style, icon = DUE_STYLE[state]
            if state == "never" and last:
                text = "още няма успешно пускане"
            c["due"].config(text=f"{icon} {text}".strip(), style=style)
            if state == "overdue":
                attention.append((f"„{sd.label}\" е {text}.", "warn"))
            elif state == "never" and sd.scheduled:
                attention.append(
                    (f"„{sd.label}\" още не е минавала успешно.", "warn")
                    if last else
                    (f"„{sd.label}\" още не е пускана.", "warn"))

        self._fill_attention(attention)
        self._fill_recent(h.recent(60))

    def _fill_attention(self, items):
        for w in self.attention.winfo_children():
            w.destroy()
        if not items:
            ttk.Label(self.attention, text="Нищо не е просрочено и няма грешки.",
                      style="CardOk.TLabel").grid(row=0, column=0, sticky="w")
            return
        for i, (text, kind) in enumerate(items[:6]):
            ttk.Label(self.attention, text="•  " + text,
                      style="CardErr.TLabel" if kind == "err" else "CardWarn.TLabel",
                      wraplength=820, justify="left"
                      ).grid(row=i, column=0, sticky="w", pady=1)

    def _fill_recent(self, rows):
        self.tree.delete(*self.tree.get_children())
        if not rows:
            self.empty_note.config(
                text="Още няма записани пускания. След първата задача тук ще се "
                     "трупа история.")
            return
        self.empty_note.config(text="")
        for r in rows:
            counts = hist.counts_of(r)
            tags = []
            if r.get("rc") not in (0, None):
                tags.append("err")
            elif r.get("dry_run"):
                tags.append("test")
            status = "готово" if r.get("rc") == 0 else f"грешка ({r.get('rc')})"
            if r.get("status") == "stopped":
                status = "спряно"
            self.tree.insert("", "end", tags=tags, values=(
                datetime.fromtimestamp(r["started_at"]).strftime("%d.%m %H:%M"),
                r.get("label", ""),
                "тест" if r.get("dry_run") else "реален",
                status,
                fmt_duration(r.get("duration")),
                summ.human(counts, limit=3),
            ))
