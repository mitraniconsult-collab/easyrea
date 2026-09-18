#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/reports.py — намира и чете файловете с отчети, които скриптовете
оставят в работната папка (sync_report_*.csv, import_report_*.csv,
missing_skus_*.txt, variations_report.xlsx …).

Целта: да не се търсят на ръка из папката. Приложението ги показва
подредени по дата, с брой редове и разбивка по колоната „action".
"""

import os
import csv
import glob
import time

from . import scripts as screg


CSV_EXT = {".csv"}
TEXT_EXT = {".txt"}


class Report:
    def __init__(self, path, script=None):
        self.path = path
        self.script = script            # ScriptDef или None
        st = os.stat(path)
        self.mtime = st.st_mtime
        self.size = st.st_size

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def ext(self):
        return os.path.splitext(self.path)[1].lower()

    @property
    def script_label(self):
        return self.script.label if self.script else "—"

    def size_text(self):
        kb = self.size / 1024.0
        if kb < 1:
            return f"{self.size} B"
        if kb < 1024:
            return f"{kb:.0f} KB"
        return f"{kb / 1024:.1f} MB"


def find_all(directory, limit_per_pattern=40):
    """Всички отчети в папката, най-новите първи."""
    out = []
    seen = set()
    for sd in screg.SCRIPTS:
        for pattern in sd.reports:
            for p in glob.glob(os.path.join(directory, pattern)):
                rp = os.path.realpath(p)
                if rp in seen or not os.path.isfile(p):
                    continue
                seen.add(rp)
                try:
                    out.append(Report(p, sd))
                except OSError:
                    pass
    out.sort(key=lambda r: r.mtime, reverse=True)
    return out


def latest_for(directory, script):
    """Най-новият отчет за конкретна задача."""
    best = None
    for pattern in script.reports:
        for p in glob.glob(os.path.join(directory, pattern)):
            if not os.path.isfile(p):
                continue
            try:
                r = Report(p, script)
            except OSError:
                continue
            if best is None or r.mtime > best.mtime:
                best = r
    return best


# ══════════════════════════════════════════════════════════════════════
#  Четене на съдържанието
# ══════════════════════════════════════════════════════════════════════
def inspect(report, max_rows=200000):
    """
    Връща {"rows": N, "actions": {...}, "columns": [...], "error": str|None}
    За CSV чете колоната 'action'. За .txt брои редовете.
    """
    info = {"rows": 0, "actions": {}, "columns": [], "error": None}
    try:
        if report.ext in CSV_EXT:
            with open(report.path, "r", encoding="utf-8-sig", newline="") as f:
                rdr = csv.DictReader(f)
                info["columns"] = rdr.fieldnames or []
                has_action = "action" in (rdr.fieldnames or [])
                for i, row in enumerate(rdr):
                    if i >= max_rows:
                        break
                    info["rows"] += 1
                    if has_action:
                        a = (row.get("action") or "").strip() or "—"
                        info["actions"][a] = info["actions"].get(a, 0) + 1
        elif report.ext in TEXT_EXT:
            with open(report.path, "r", encoding="utf-8") as f:
                info["rows"] = sum(1 for line in f if line.strip())
        else:
            info["rows"] = -1        # xlsx — не го отваряме, за да е бързо
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        info["error"] = str(e)
    return info


def compare(prev_actions, curr_actions):
    """
    Разликата между два отчета по действия.
    Връща [(действие, преди, сега, разлика)], подредено по големина на разликата.
    """
    keys = set(prev_actions) | set(curr_actions)
    rows = []
    for k in keys:
        a = prev_actions.get(k, 0)
        b = curr_actions.get(k, 0)
        rows.append((k, a, b, b - a))
    rows.sort(key=lambda r: (-abs(r[3]), r[0]))
    return rows


def open_in_os(path):
    """Отваря файла с програмата по подразбиране (Excel и т.н.)."""
    import sys
    import subprocess
    if os.name == "nt":
        os.startfile(path)                                       # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def age_text(mtime):
    days = (time.time() - mtime) / 86400.0
    if days < 1 / 24:
        return "преди малко"
    if days < 1:
        return f"преди {int(days * 24)} ч"
    if days < 30:
        n = int(days)
        return f"преди {n} " + ("ден" if n == 1 else "дни")
    return time.strftime("%d.%m.%Y", time.localtime(mtime))
