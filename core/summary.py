#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/summary.py — изважда числата от блока „ОБОБЩЕНИЕ", който всеки
скрипт печата накрая.

Скриптовете завършват така:

    === ОБОБЩЕНИЕ ===
      IN_STOCK: 8412
      ARRIVING: 240
      MISSING: 96
      (пропуснати — други доставчици: 1203)

Тук превръщаме това в {"IN_STOCK": 8412, "ARRIVING": 240, …}, за да може
таблото да показва резултата, без да се отваря CSV-то.
"""

import re


_HEAD = re.compile(r"ОБОБЩЕНИЕ")
_PAIR = re.compile(r"^\s*([A-ZА-Я_][A-ZА-Я0-9_ ]*?)\s*:\s*(\d+)\s*$")
_SKIPPED = re.compile(r"пропуснати[^:]*:\s*(\d+)")
_REPORT = re.compile(r"^\s*Отчет(?:\s+записан)?\s*:\s*(.+?)\s*$")

# Как да се чете всеки ключ на човешки език
LABELS = {
    "IN_STOCK": "в наличност",
    "ARRIVING": "на път",
    "MISSING": "липсващи",
    "SET": "записани дати",
    "DELETE": "изтрити дати",
    "SKIP": "без промяна",
    "NO_MATCH": "няма в easyrea",
    "ERROR": "грешки",
    "CREATED": "създадени",
    "SKIP_NO_PRICE": "без цена",
    "SKIP_NO_IMAGE": "без снимка",
    "SKIP_NO_TITLE": "без заглавие",
    "UPDATED": "обновени",
    "SKIPPED": "пропуснати",
}

# Кои ключове са „лоши" — показват се в червено
BAD_KEYS = {"ERROR", "MISSING", "SKIP_NO_PRICE", "SKIP_NO_IMAGE", "SKIP_NO_TITLE"}


def parse(lines):
    """
    lines — списък от редове (или един текст). Връща:
        {"counts": {...}, "skipped_other": int|None, "report": path|None}
    """
    if isinstance(lines, str):
        lines = lines.splitlines()

    counts = {}
    skipped_other = None
    report = None
    in_summary = False

    for raw in lines:
        line = raw.rstrip("\n")

        if _HEAD.search(line):
            in_summary = True
            continue

        m = _REPORT.match(line)
        if m:
            report = m.group(1)
            continue

        m = _SKIPPED.search(line)
        if m:
            skipped_other = int(m.group(1))
            continue

        if in_summary:
            m = _PAIR.match(line)
            if m:
                key = m.group(1).strip()
                counts[key] = int(m.group(2))
            elif line.strip().startswith(">>>"):
                in_summary = False

    return {"counts": counts, "skipped_other": skipped_other, "report": report}


def human(counts, limit=4):
    """'8412 в наличност · 240 на път · 96 липсващи'"""
    if not counts:
        return ""
    items = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return " · ".join(f"{v} {LABELS.get(k, k.lower())}" for k, v in items)
