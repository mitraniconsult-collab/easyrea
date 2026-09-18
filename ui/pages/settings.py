#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/pages/settings.py — достъп (credentials) и настройки на приложението.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .. import theme
from ..theme import Fonts
from core.config import CRED_FIELDS
from core import healthcheck as hc


_STATUS_STYLE = {
    hc.OK:   ("CardOk.TLabel", "✓"),
    hc.WARN: ("CardWarn.TLabel", "!"),
    hc.FAIL: ("CardErr.TLabel", "✗"),
    hc.SKIP: ("CardMuted.TLabel", "–"),
}


class SettingsPage(ttk.Frame):

    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._masked = []

        self.columnconfigure(0, weight=1)

        head = ttk.Frame(self, padding=(0, 0, 0, 10))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Настройки", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Данните се пазят локално в config.json и се подават "
                             "на скриптовете при всяко стартиране.",
                  style="Sub.TLabel").grid(row=1, column=0, sticky="w")

        self._results = queue.Queue()
        self._checking = False

        self._build_creds()
        self._build_healthcheck()
        self._build_prefs()
        self.after(200, self._poll_results)

    # ══════════════════════════════════════════════════════════════════
    def _build_creds(self):
        frame = ttk.LabelFrame(self, text="Достъп", padding=14)
        frame.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)

        for i, (key, label, secret) in enumerate(CRED_FIELDS):
            ttk.Label(frame, text=label + ":", style="Card.TLabel").grid(
                row=i, column=0, sticky="w", pady=5, padx=(0, 12))
            entry = ttk.Entry(frame, textvariable=self.app.cred_vars[key],
                              show="•" if secret else "")
            entry.grid(row=i, column=1, sticky="ew", pady=5)
            if secret:
                self._masked.append(entry)

        row = ttk.Frame(frame, style="Card.TFrame")
        row.grid(row=len(CRED_FIELDS), column=0, columnspan=2, sticky="ew", pady=(12, 0))
        row.columnconfigure(0, weight=1)

        ttk.Checkbutton(row, text="Покажи паролите и ключовете",
                        style="Card.TCheckbutton", variable=self.app.show_secrets,
                        command=self._toggle).grid(row=0, column=0, sticky="w")
        ttk.Button(row, text="Запази", style="Accent.TButton",
                   command=self._save).grid(row=0, column=1, sticky="e")

        self.warn = ttk.Label(frame, text="", style="CardErr.TLabel",
                              wraplength=620, justify="left")
        self.warn.grid(row=len(CRED_FIELDS) + 1, column=0, columnspan=2,
                       sticky="w", pady=(10, 0))
        self.refresh_warning()

    # ══════════════════════════════════════════════════════════════════
    #  Проверка на връзката
    # ══════════════════════════════════════════════════════════════════
    def _build_healthcheck(self):
        frame = ttk.LabelFrame(self, text="Проверка на връзката", padding=14)
        frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame,
                  text="Пуска бързи заявки към easyrea, Shopify и Anthropic. "
                       "Нищо не се променя — само се проверява дали достъпът работи.",
                  style="CardMuted.TLabel", wraplength=640, justify="left"
                  ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.check_rows = {}
        for i, (cid, label, _fn) in enumerate(hc.CHECKS, start=1):
            icon = ttk.Label(frame, text="", style="CardMuted.TLabel", width=2)
            icon.grid(row=i, column=0, sticky="w")
            ttk.Label(frame, text=label + ":", style="Card.TLabel", width=20
                      ).grid(row=i, column=1, sticky="w")
            msg = ttk.Label(frame, text="—", style="CardMuted.TLabel",
                            wraplength=520, justify="left")
            msg.grid(row=i, column=2, sticky="w", pady=1)
            self.check_rows[cid] = (icon, msg)

        row = ttk.Frame(frame, style="Card.TFrame")
        row.grid(row=len(hc.CHECKS) + 1, column=0, columnspan=3,
                 sticky="ew", pady=(12, 0))
        row.columnconfigure(1, weight=1)

        self.check_btn = ttk.Button(row, text="Провери сега", style="Accent.TButton",
                                    command=self.run_check)
        self.check_btn.grid(row=0, column=0, sticky="w")
        self.verdict_lbl = ttk.Label(row, text="", style="CardMuted.TLabel",
                                     wraplength=440, justify="left")
        self.verdict_lbl.grid(row=0, column=1, sticky="w", padx=(14, 0))

    def run_check(self):
        if self._checking:
            return
        self._checking = True
        self.check_btn.config(state="disabled", text="Проверява се…")
        self.verdict_lbl.config(text="", style="CardMuted.TLabel")
        for cid, (icon, msg) in self.check_rows.items():
            icon.config(text="", style="CardMuted.TLabel")
            msg.config(text="чака…", style="CardMuted.TLabel")

        ctx = {k: v.get().strip() for k, v in self.app.cred_vars.items()}
        ctx["scripts_dir"] = self.app.dir_now

        def worker():
            def on_result(cid, status, message):
                self._results.put(("row", cid, status, message))
            try:
                res = hc.run_all(ctx, on_result=on_result)
                self._results.put(("done", hc.verdict(res)))
            except Exception as e:                               # noqa: BLE001
                self._results.put(("done", (hc.FAIL, f"Проверката се счупи: {e}")))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self):
        try:
            while True:
                item = self._results.get_nowait()
                if item[0] == "row":
                    _, cid, status, message = item
                    icon, msg = self.check_rows[cid]
                    style, sign = _STATUS_STYLE[status]
                    icon.config(text=sign, style=style)
                    msg.config(text=message, style=style if status != hc.OK
                               else "Card.TLabel")
                else:
                    status, text = item[1]
                    style, _ = _STATUS_STYLE[status]
                    self.verdict_lbl.config(text=text, style=style)
                    self.check_btn.config(state="normal", text="Провери сега")
                    self._checking = False
                    self.app.set_status("Проверка: " + text)
        except queue.Empty:
            pass
        self.after(200, self._poll_results)

    # ══════════════════════════════════════════════════════════════════
    def _build_prefs(self):
        frame = ttk.LabelFrame(self, text="Приложение", padding=14)
        frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        frame.columnconfigure(0, weight=1)

        ttk.Checkbutton(frame, text="Записвай лога автоматично в подпапка logs\\",
                        style="Card.TCheckbutton", variable=self.app.autosave_logs
                        ).grid(row=0, column=0, sticky="w")
        ttk.Label(frame,
                  text="Всяка задача получава свой файл с дата и час, за да може "
                       "да се провери какво е станало след затваряне на прозореца.",
                  style="CardMuted.TLabel", wraplength=620, justify="left"
                  ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        ttk.Label(frame, text="config.json се пази в открит текст. Не го качвай "
                              "в git и не го изпращай по имейл.",
                  style="CardMuted.TLabel", wraplength=620, justify="left"
                  ).grid(row=2, column=0, sticky="w")

        row = ttk.Frame(frame, style="Card.TFrame")
        row.grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Button(row, text="Отвори папката с логовете", style="Secondary.TButton",
                   command=self._open_logs).pack(side="left")
        ttk.Button(row, text="Изчисти история над 6 месеца", style="Secondary.TButton",
                   command=self._purge).pack(side="left", padx=(8, 0))

        self.hist_lbl = ttk.Label(frame, text="", style="CardMuted.TLabel")
        self.hist_lbl.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.refresh_history_note()

    # ══════════════════════════════════════════════════════════════════
    def _toggle(self):
        show = "" if self.app.show_secrets.get() else "•"
        for e in self._masked:
            e.config(show=show)

    def _save(self):
        try:
            self.app.save_config()
            self.app.set_status("Настройките са запазени.")
            self.refresh_warning()
        except OSError as e:
            messagebox.showerror("Грешка", f"Неуспешен запис на config.json:\n{e}")

    def refresh_warning(self):
        missing = [label for key, label, _ in CRED_FIELDS
                   if not self.app.cred_vars[key].get().strip()]
        if missing:
            self.warn.config(
                text="Липсват: " + ", ".join(missing) +
                     ".  Скриптовете ще спрат веднага, ако тръгнат без тях.")
        else:
            self.warn.config(text="")

    def refresh_history_note(self):
        h = self.app.history
        if not h.enabled:
            self.hist_lbl.config(text="Историята не е достъпна (проблем с history.db).")
            return
        n = len(h.recent(limit=100000))
        self.hist_lbl.config(
            text=f"Записани пускания в историята: {n}  ·  {h.path}")

    def _purge(self):
        n = self.app.history.purge_older_than(180)
        self.app.set_status(f"Изтрити стари записи: {n}")
        self.refresh_history_note()
        try:
            self.app.pages["dashboard"].refresh()
        except Exception:                                        # noqa: BLE001
            pass

    def _open_logs(self):
        path = self.app.log_dir
        os.makedirs(path, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(path)                              # noqa: S606
            elif sys_is_mac():
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except OSError as e:
            messagebox.showinfo("Папка с логове", f"{path}\n\n({e})")


def sys_is_mac():
    import sys
    return sys.platform == "darwin"
