#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/config.py — четене и запис на настройките (config.json).

Пази креденшълите, опциите и състоянието на прозореца. Файлът е в
ОТКРИТ текст (по изискване), затова на Linux/macOS му слагаме права 600,
а в .gitignore е изключен.
"""

import os
import json


# (env ключ, етикет в интерфейса, тайна ли е)
CRED_FIELDS = [
    ("EASYREA_LOGIN",         "EasyRea вход",            False),
    ("EASYREA_PASSWORD",      "EasyRea парола",          True),
    ("SHOPIFY_STORE",         "Shopify магазин",         False),
    ("SHOPIFY_CLIENT_ID",     "Shopify Client ID",       False),
    ("SHOPIFY_CLIENT_SECRET", "Shopify Client Secret",   True),
    ("SHOPIFY_LOCATION_ID",   "Shopify Location ID",     False),
    ("ANTHROPIC_API_KEY",     "Anthropic API ключ",      True),
]

CRED_KEYS = [k for k, _, _ in CRED_FIELDS]

DEFAULTS = {
    "SHOPIFY_LOCATION_ID": "gid://shopify/Location/81609621771",
    "BATCH_SIZE": "500",
    "BATCH_NUMBER": "1",
    "DRY_RUN": True,
    "SCRIPTS_DIR": "",
    "WINDOW": "",          # напр. "1180x740+120+60"
    "AUTOSAVE_LOGS": True,
}


class Config(dict):
    """Обикновен dict със запис/четене от файл."""

    def __init__(self, path):
        super().__init__(DEFAULTS)
        self.path = path
        self.load_error = None

    # ── четене ────────────────────────────────────────────────────────
    def load(self):
        if not os.path.isfile(self.path):
            return self
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.update(data)
        except (OSError, json.JSONDecodeError) as e:
            self.load_error = str(e)
        return self

    # ── запис ─────────────────────────────────────────────────────────
    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(self), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)      # атомарен запис — без счупен файл
        if os.name != "nt":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    # ── помощни ───────────────────────────────────────────────────────
    def creds(self):
        return {k: str(self.get(k, "") or "").strip() for k in CRED_KEYS}

    def missing_creds(self):
        return [k for k, v in self.creds().items() if not v]

    def text(self, key, default=""):
        return str(self.get(key, default) or "").strip()

    def flag(self, key, default=False):
        return bool(self.get(key, default))
