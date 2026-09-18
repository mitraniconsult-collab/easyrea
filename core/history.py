#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/history.py — локална история на пусканията (SQLite).

Записва всяко пускане: коя задача, кога, колко е траяло, с какъв код е
приключило, колко грешки е имало и какви са били числата в обобщението.
Оттам таблото знае „кога за последно" и „какво излезе".

Файлът е обикновен .db до config.json. Не съдържа пароли.
"""

import os
import json
import time
import sqlite3
from datetime import datetime, timedelta


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    script       TEXT    NOT NULL,
    label        TEXT    NOT NULL,
    started_at   REAL    NOT NULL,
    finished_at  REAL,
    duration     REAL,
    rc           INTEGER,
    status       TEXT,
    errors       INTEGER DEFAULT 0,
    dry_run      INTEGER DEFAULT 1,
    done         INTEGER DEFAULT 0,
    total        INTEGER DEFAULT 0,
    summary      TEXT,
    report       TEXT,
    log_path     TEXT,
    args         TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_script ON runs(script, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_time   ON runs(started_at DESC);
"""


class History:

    def __init__(self, path):
        self.path = path
        self.enabled = True
        try:
            self._init_db()
        except sqlite3.Error:
            # Историята е удобство, не е критична — приложението работи и без нея.
            self.enabled = False

    # ── вътрешни ──────────────────────────────────────────────────────
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ── запис ─────────────────────────────────────────────────────────
    def record(self, task, dry_run):
        """Записва приключила задача. Връща id или None."""
        if not self.enabled:
            return None
        summ = task.summary or {}
        counts = summ.get("counts") or {}
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO runs (script, label, started_at, finished_at, "
                    " duration, rc, status, errors, dry_run, done, total, "
                    " summary, report, log_path, args) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (task.script.file, task.label, task.started_at or time.time(),
                     task.finished_at, task.elapsed, task.rc, task.status,
                     task.error_count, 1 if dry_run else 0,
                     task.done, task.total,
                     json.dumps(counts, ensure_ascii=False),
                     summ.get("report") or "",
                     task.log_path or "",
                     " ".join(task.args)))
                return cur.lastrowid
        except sqlite3.Error:
            return None

    # ── четене ────────────────────────────────────────────────────────
    def recent(self, limit=100):
        if not self.enabled:
            return []
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                    (limit,)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []

    def last_for(self, script_file, successful_only=False):
        if not self.enabled:
            return None
        q = "SELECT * FROM runs WHERE script = ?"
        if successful_only:
            q += " AND rc = 0"
        q += " ORDER BY started_at DESC LIMIT 1"
        try:
            with self._conn() as c:
                r = c.execute(q, (script_file,)).fetchone()
            return dict(r) if r else None
        except sqlite3.Error:
            return None

    def last_two(self, script_file):
        """Последните две пускания — за сравнение „какво се промени"."""
        if not self.enabled:
            return []
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT * FROM runs WHERE script = ? AND rc = 0 "
                    "ORDER BY started_at DESC LIMIT 2", (script_file,)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []

    def purge_older_than(self, days=180):
        if not self.enabled:
            return 0
        cutoff = time.time() - days * 86400
        try:
            with self._conn() as c:
                cur = c.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
                return cur.rowcount
        except sqlite3.Error:
            return 0


# ══════════════════════════════════════════════════════════════════════
#  Помощни за таблото
# ══════════════════════════════════════════════════════════════════════
def counts_of(row):
    """Числата от обобщението на един запис."""
    if not row:
        return {}
    try:
        return json.loads(row.get("summary") or "{}")
    except (ValueError, AttributeError):
        return {}


def ago(ts):
    """'преди 3 дни' / 'днес в 09:14'"""
    if not ts:
        return "никога"
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    delta = now - dt
    if delta.total_seconds() < 60:
        return "току-що"
    if dt.date() == now.date():
        return f"днес в {dt:%H:%M}"
    if dt.date() == (now - timedelta(days=1)).date():
        return f"вчера в {dt:%H:%M}"
    days = delta.days
    if days < 7:
        return f"преди {days} дни"
    if days < 30:
        w = days // 7
        return f"преди {w} седмица" if w == 1 else f"преди {w} седмици"
    return f"{dt:%d.%m.%Y}"


def due_state(script, last_row):
    """
    Връща (състояние, текст) за график на задача.
    Състояния: "none" (няма график), "ok", "soon", "overdue", "never"
    """
    if not script.scheduled:
        return ("none", "")
    if not last_row or not last_row.get("started_at"):
        return ("never", "не е пускана")

    days = (time.time() - last_row["started_at"]) / 86400.0
    left = script.every_days - days

    if left < 0:
        n = int(abs(left)) + 1
        return ("overdue", f"просрочено с {n} " + ("ден" if n == 1 else "дни"))
    if left < 1:
        return ("soon", "днес")
    n = int(left)
    return ("ok", f"след {n} " + ("ден" if n == 1 else "дни"))
