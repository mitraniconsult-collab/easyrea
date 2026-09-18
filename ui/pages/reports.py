#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/pages/reports.py — файловете с отчети в работната папка.

Показва ги подредени по дата, с брой редове и разбивка по действия,
и сравнява два поредни отчета от една и съща задача („този път 400
продукта повече отидоха в MISSING").
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox

from .. import theme
from ..theme import Fonts
from core import reports as rep


class ReportsPage(ttk.Frame):

    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._items = {}          # tree iid -> Report
        self._selected = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ttk.Frame(self, padding=(0, 0, 0, 10))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Отчети", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Файловете, които скриптовете оставят в работната папка.",
                  style="Sub.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Button(head, text="Обнови", style="Secondary.TButton",
                   command=self.refresh).grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, uniform="r")
        body.columnconfigure(1, weight=2, uniform="r")
        body.rowconfigure(0, weight=1)

        self._build_list(body)
        self._build_detail(body)

    # ══════════════════════════════════════════════════════════════════
    def _build_list(self, parent):
        frame = ttk.LabelFrame(parent, text="Файлове", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("name", "task", "when", "size")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=16)
        for key, text, width, stretch in (
                ("name", "Файл", 260, True),
                ("task", "Задача", 180, False),
                ("when", "Кога", 110, False),
                ("size", "Размер", 80, False)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, stretch=stretch, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._open())

        self.empty = ttk.Label(frame, text="", style="CardMuted.TLabel",
                               wraplength=440, justify="left")
        self.empty.grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _build_detail(self, parent):
        frame = ttk.LabelFrame(parent, text="Съдържание", padding=12)
        frame.grid(row=0, column=1, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        self.title_lbl = ttk.Label(frame, text="Избери файл отляво.",
                                   style="CardBold.TLabel",
                                   wraplength=320, justify="left")
        self.title_lbl.grid(row=0, column=0, sticky="w")

        self.meta_lbl = ttk.Label(frame, text="", style="CardMuted.TLabel",
                                  wraplength=320, justify="left")
        self.meta_lbl.grid(row=1, column=0, sticky="w", pady=(4, 8))

        self.detail = tk.Text(frame, height=14, wrap="word", state="disabled",
                              font=(Fonts.mono, 9), relief="flat", borderwidth=0,
                              background="#f7f8fa", foreground=theme.TEXT,
                              padx=8, pady=6)
        self.detail.grid(row=2, column=0, sticky="nsew")
        self.detail.tag_configure("up", foreground=theme.DANGER)
        self.detail.tag_configure("down", foreground=theme.OK)
        self.detail.tag_configure("head", font=(Fonts.mono, 9, "bold"))

        btns = ttk.Frame(frame)
        btns.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        btns.columnconfigure(0, weight=1)
        self.open_btn = ttk.Button(btns, text="Отвори файла", style="Accent.TButton",
                                   command=self._open, state="disabled")
        self.open_btn.grid(row=0, column=0, sticky="ew")
        ttk.Button(btns, text="Отвори папката", style="Secondary.TButton",
                   command=self._open_folder).grid(row=1, column=0, sticky="ew", pady=(6, 0))

    # ══════════════════════════════════════════════════════════════════
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        self._selected = None
        self.open_btn.config(state="disabled")
        self._set_detail("")
        self.title_lbl.config(text="Избери файл отляво.")
        self.meta_lbl.config(text="")

        d = self.app.dir_now
        try:
            found = rep.find_all(d)
        except OSError as e:
            self.empty.config(text=f"Папката не се чете: {e}")
            return

        if not found:
            self.empty.config(
                text=f"В {d} още няма отчети. Пусни задача от „Действия“ — "
                     f"файловете ще се появят тук.")
            return
        self.empty.config(text="")

        for r in found:
            iid = self.tree.insert("", "end", values=(
                r.name, r.script_label, rep.age_text(r.mtime), r.size_text()))
            self._items[iid] = r

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        report = self._items.get(sel[0])
        if not report:
            return
        self._selected = report
        self.open_btn.config(state="normal")
        self.title_lbl.config(text=report.name)

        info = rep.inspect(report)
        if info["error"]:
            self.meta_lbl.config(text=f"Файлът не се чете: {info['error']}")
            self._set_detail("")
            return

        if info["rows"] < 0:
            self.meta_lbl.config(text=f"{report.script_label} · {report.size_text()}")
            self._set_detail("Excel файл — отвори го, за да го видиш.\n")
            return

        self.meta_lbl.config(
            text=f"{report.script_label} · {info['rows']} реда · {report.size_text()}")

        lines = []
        tags = []
        if info["actions"]:
            lines.append(("Разбивка по действие\n", "head"))
            for k, v in sorted(info["actions"].items(), key=lambda kv: -kv[1]):
                lines.append((f"  {k:<16} {v}\n", None))

        cmp_rows = self._comparison(report, info)
        if cmp_rows:
            lines.append(("\nСпрямо предишния отчет\n", "head"))
            for k, a, b, diff in cmp_rows:
                if diff == 0:
                    lines.append((f"  {k:<16} {b}   (без промяна)\n", None))
                else:
                    sign = "+" if diff > 0 else ""
                    tag = "up" if diff > 0 else "down"
                    lines.append((f"  {k:<16} {a} → {b}   {sign}{diff}\n", tag))

        self._set_detail(lines)

    def _comparison(self, report, info):
        """Търси предишния отчет от същата задача и сравнява действията."""
        if not report.script or not info.get("actions"):
            return None
        same = [r for r in rep.find_all(self.app.dir_now)
                if r.script and r.script.file == report.script.file]
        same.sort(key=lambda r: r.mtime, reverse=True)
        try:
            pos = next(i for i, r in enumerate(same)
                       if os.path.realpath(r.path) == os.path.realpath(report.path))
        except StopIteration:
            return None
        if pos + 1 >= len(same):
            return None
        prev = rep.inspect(same[pos + 1])
        if prev["error"] or not prev["actions"]:
            return None
        return rep.compare(prev["actions"], info["actions"])

    def _set_detail(self, content):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        if isinstance(content, str):
            self.detail.insert("end", content)
        else:
            for text, tag in content:
                self.detail.insert("end", text, tag or "")
        self.detail.config(state="disabled")

    # ══════════════════════════════════════════════════════════════════
    def _open(self):
        if not self._selected:
            return
        try:
            rep.open_in_os(self._selected.path)
        except OSError as e:
            messagebox.showerror("Грешка", f"Файлът не може да се отвори:\n{e}")

    def _open_folder(self):
        try:
            rep.open_in_os(self.app.dir_now)
        except OSError as e:
            messagebox.showinfo("Папка", f"{self.app.dir_now}\n\n({e})")
