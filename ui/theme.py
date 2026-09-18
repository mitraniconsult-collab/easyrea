#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui/theme.py — цветове, шрифтове и ttk стилове на едно място.
"""

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont


# ── Палитра ───────────────────────────────────────────────────────────
BG         = "#eceef2"    # общ фон
SIDEBAR    = "#1f2733"    # страничната лента
SIDEBAR_AC = "#2f6feb"    # активен елемент в лентата
SIDEBAR_FG = "#c3ccd8"
CARD       = "#ffffff"
TEXT       = "#1f2933"
MUTED      = "#6b7280"
BORDER     = "#d7dce3"

ACCENT     = "#2f6feb"
ACCENT_AC  = "#2257c5"
DANGER     = "#dc2626"
DANGER_AC  = "#b91c1c"
OK         = "#16a34a"
WARN       = "#b45309"

# Лента за режима
MODE_TEST  = "#64748b"    # сиво — тест
MODE_REAL  = "#ea580c"    # оранжево — реален запис

# Лог
LOG_BG     = "#1b1f24"
LOG_FG     = "#d7dde3"
LOG_ERR    = "#ff6b6b"
LOG_WARN   = "#f0b429"
LOG_OK     = "#5ed68f"
LOG_HEAD   = "#7aa7ff"
LOG_MUTED  = "#7d8794"


def pick_font(root, candidates):
    avail = set(tkfont.families(root))
    for c in candidates:
        if c in avail:
            return c
    return candidates[-1]


class Fonts:
    """Попълва се в apply_theme()."""
    family = "Arial"
    mono = "Courier New"
    base = ("Arial", 10)
    bold = ("Arial", 10, "bold")
    small = ("Arial", 9)
    small_bold = ("Arial", 9, "bold")
    title = ("Arial", 17, "bold")
    h2 = ("Arial", 12, "bold")
    nav = ("Arial", 11)


def apply_theme(root):
    s = ttk.Style(root)
    try:
        s.theme_use("clam")       # clam позволява цветни бутони
    except tk.TclError:
        pass

    fam = pick_font(root, ["Segoe UI", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"])
    mono = pick_font(root, ["Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"])

    Fonts.family = fam
    Fonts.mono = mono
    Fonts.base = (fam, 10)
    Fonts.bold = (fam, 10, "bold")
    Fonts.small = (fam, 9)
    Fonts.small_bold = (fam, 9, "bold")
    Fonts.title = (fam, 17, "bold")
    Fonts.h2 = (fam, 12, "bold")
    Fonts.nav = (fam, 11)

    for fn in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(fn).configure(family=fam, size=10)
        except tk.TclError:
            pass

    root.configure(bg=BG)

    s.configure(".", background=BG, foreground=TEXT, font=Fonts.base)
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=CARD)
    s.configure("Sidebar.TFrame", background=SIDEBAR)

    s.configure("TLabel", background=BG, foreground=TEXT, font=Fonts.base)
    s.configure("Title.TLabel", background=BG, foreground=TEXT, font=Fonts.title)
    s.configure("H2.TLabel", background=BG, foreground=TEXT, font=Fonts.h2)
    s.configure("CardH2.TLabel", background=CARD, foreground=TEXT, font=Fonts.h2)
    s.configure("Sub.TLabel", background=BG, foreground=MUTED, font=Fonts.base)
    s.configure("Card.TLabel", background=CARD, foreground=TEXT, font=Fonts.base)
    s.configure("CardBold.TLabel", background=CARD, foreground=TEXT, font=Fonts.bold)
    s.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=Fonts.small)
    s.configure("CardOk.TLabel", background=CARD, foreground=OK, font=Fonts.small_bold)
    s.configure("CardErr.TLabel", background=CARD, foreground=DANGER, font=Fonts.small_bold)
    s.configure("CardWarn.TLabel", background=CARD, foreground=WARN, font=Fonts.small_bold)
    s.configure("Status.TLabel", background=BG, foreground=MUTED, font=Fonts.base)

    s.configure("TLabelframe", background=CARD, bordercolor=BORDER,
                relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=CARD, foreground=TEXT, font=Fonts.bold)

    s.configure("TCheckbutton", background=BG, foreground=TEXT, font=Fonts.base)
    s.map("TCheckbutton", background=[("active", BG)])
    s.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=Fonts.base)
    s.map("Card.TCheckbutton", background=[("active", CARD)],
          indicatorcolor=[("selected", ACCENT)])

    s.configure("TEntry", fieldbackground="white", foreground=TEXT,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                insertcolor=TEXT, padding=5, relief="flat")
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])

    s.configure("Accent.TButton", background=ACCENT, foreground="white",
                font=Fonts.bold, borderwidth=0, padding=(14, 11))
    s.map("Accent.TButton",
          background=[("active", ACCENT_AC), ("pressed", ACCENT_AC), ("disabled", "#aeb7c4")],
          foreground=[("disabled", "#eef0f3")])

    s.configure("Secondary.TButton", background="#e4e8ee", foreground=TEXT,
                borderwidth=0, padding=(12, 8), font=Fonts.base)
    s.map("Secondary.TButton",
          background=[("active", "#d6dce4"), ("disabled", "#eef0f3")],
          foreground=[("disabled", "#aab2bd")])

    s.configure("Danger.TButton", background=DANGER, foreground="white",
                font=Fonts.bold, borderwidth=0, padding=(14, 11))
    s.map("Danger.TButton",
          background=[("active", DANGER_AC), ("pressed", DANGER_AC), ("disabled", "#e7bcbc")],
          foreground=[("disabled", "#f3eaea")])

    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#dde2e9",
                bordercolor="#dde2e9", lightcolor=ACCENT, darkcolor=ACCENT, thickness=14)

    s.configure("Treeview", background="white", fieldbackground="white",
                foreground=TEXT, rowheight=28, borderwidth=0, font=Fonts.base)
    s.configure("Treeview.Heading", background="#e4e8ee", foreground=TEXT,
                font=Fonts.small_bold, relief="flat")
    s.map("Treeview", background=[("selected", "#dbe6ff")],
          foreground=[("selected", TEXT)])

    return s
