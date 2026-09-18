#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runtime.py — общи настройки за всички скриптове.
================================================

Тук е ЕДНО място, което решава:
  • в тестов (DRY RUN) или в реален режим работи скриптът;
  • коя партида се обработва (BATCH_SIZE / BATCH_NUMBER);
  • дали са налични всички креденшъли — ако не, спира ВЕДНАГА с ясно
    съобщение, вместо да гърми насред работата.

ПРИОРИТЕТ на настройките (по-долното печели):
    1. стойността по подразбиране в скрипта
    2. environment променлива          (DRY_RUN=1 / DRY_RUN=0)
    3. аргумент от командния ред       (--dry-run / --real-run)

Така приложението (app.py) винаги командва режима, а от cron/Task
Scheduler можеш да зададеш каквото ти трябва.

ВАЖНО: тук НЯМА никакви пароли и ключове. Всичко се чете от
environment. Ако липсва — скриптът спира.
"""

import os
import sys

__all__ = [
    "dry_run", "batch_size", "batch_number", "force",
    "require_env", "env_str", "env_int", "print_mode_banner",
]


# ════════════════════════════════════════════════════════════════════════
#  Четене на стойности
# ════════════════════════════════════════════════════════════════════════
_TRUE = {"1", "true", "yes", "y", "on", "да"}
_FALSE = {"0", "false", "no", "n", "off", "не"}


def _argv():
    return [a.strip().lower() for a in sys.argv[1:]]


def _arg_value(name):
    """Връща стойността на --name X или --name=X, ако е подадена."""
    args = sys.argv[1:]
    flag = f"--{name}"
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1].strip()
        if a.startswith(flag + "="):
            return a.split("=", 1)[1].strip()
    return None


def dry_run(default=True):
    """
    True  = само отчет, НИЩО не се променя.
    False = реален режим, промените се прилагат.

    По подразбиране е True (безопасно). Приложението и планировчикът
    подават явна стойност.
    """
    value = bool(default)

    raw = os.environ.get("DRY_RUN")
    if raw is not None and raw.strip() != "":
        r = raw.strip().lower()
        if r in _TRUE:
            value = True
        elif r in _FALSE:
            value = False

    args = _argv()
    if "--dry-run" in args:
        value = True
    if "--real-run" in args or "--no-dry-run" in args:
        value = False

    return value


def force():
    """--force изключва предпазната спирачка за масови промени."""
    return "--force" in _argv() or os.environ.get("FORCE", "").strip().lower() in _TRUE


def env_int(name, default):
    """Цяло положително число от --name / env / default."""
    raw = _arg_value(name.lower().replace("_", "-"))
    if raw is None:
        raw = os.environ.get(name, "")
    raw = (raw or "").strip()
    if not raw:
        return int(default)
    try:
        val = int(raw)
    except ValueError:
        sys.exit(f"[НАСТРОЙКА] {name} трябва да е цяло число, а е: {raw!r}")
    if val <= 0:
        sys.exit(f"[НАСТРОЙКА] {name} трябва да е положително число, а е: {val}")
    return val


def batch_size(default=500):
    return env_int("BATCH_SIZE", default)


def batch_number(default=1):
    return env_int("BATCH_NUMBER", default)


def env_str(name, default=""):
    return (os.environ.get(name, default) or "").strip()


# ════════════════════════════════════════════════════════════════════════
#  Креденшъли — задължително от environment, никога от кода
# ════════════════════════════════════════════════════════════════════════
_HINT = {
    "EASYREA_LOGIN":         "EasyRea вход",
    "EASYREA_PASSWORD":      "EasyRea парола",
    "SHOPIFY_STORE":         "Shopify магазин (напр. име.myshopify.com)",
    "SHOPIFY_CLIENT_ID":     "Shopify Client ID",
    "SHOPIFY_CLIENT_SECRET": "Shopify Client Secret",
    "SHOPIFY_LOCATION_ID":   "Shopify Location ID",
    "ANTHROPIC_API_KEY":     "Anthropic API ключ",
}


def require_env(*names):
    """
    Проверява, че всички изброени променливи са зададени и НЕ са празни.
    При липса — спира с ясен списък какво точно да се попълни.
    Връща dict {име: стойност}.
    """
    values, missing = {}, []
    for n in names:
        v = env_str(n)
        if not v:
            missing.append(n)
        values[n] = v

    if missing:
        print("\n" + "!" * 70)
        print("СПИРАМ: липсват задължителни настройки за достъп.")
        print("!" * 70)
        for n in missing:
            print(f"   • {n}   — {_HINT.get(n, '')}")
        print("\nПопълни ги в приложението (полетата горе вляво) и натисни")
        print("„Запази настройките\", или ги задай като environment променливи.")
        print("Тайните НЕ се пазят в кода на скриптовете.\n")
        sys.exit(2)

    return values


# ════════════════════════════════════════════════════════════════════════
#  Визуално обозначаване на режима
# ════════════════════════════════════════════════════════════════════════
def print_mode_banner(script_name, is_dry, extra=""):
    line = "═" * 70
    print(line)
    if is_dry:
        print(f"  {script_name}   ·   РЕЖИМ: ТЕСТ (DRY RUN)")
        print("  Нищо няма да бъде променено. Само се пише отчет.")
    else:
        print(f"  {script_name}   ·   РЕЖИМ: РЕАЛЕН")
        print("  ВНИМАНИЕ: промените ЩЕ бъдат приложени в Shopify.")
    if extra:
        print(f"  {extra}")
    print(line, flush=True)
