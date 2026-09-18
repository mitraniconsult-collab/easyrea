#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/healthcheck.py — бърза проверка „всичко ли е наред", преди да се
пусне задача, която трае половин час.

Проверява:
  1. Python пакетите (requests, openpyxl)
  2. Файловете в работната папка (скриптове + runtime.py)
  3. EasyRea — логин и xsrf токен
  4. Shopify — токен, име на магазина И дали Location ID-то съществува
  5. Anthropic — валиден ли е ключът

Всяка проверка връща (статус, съобщение). Статуси:
    "ok"   — наред
    "warn" — работи, но има какво да се оправи
    "fail" — няма да проработи
    "skip" — не е проверявана (липсват данни)

Мрежовите проверки са бързи (кратки таймаути) и НЕ променят нищо.
"""

import os
import json
import base64

from . import scripts as screg


OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

TIMEOUT = 20
SHOPIFY_API_VER = "2026-04"
EASYREA_BASE = "https://api-prod.easyrea.com/private/api/easyrea"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")


# ══════════════════════════════════════════════════════════════════════
#  1. Пакети
# ══════════════════════════════════════════════════════════════════════
def check_packages(ctx):
    missing = []
    for mod, why in (("requests", "задължителен за всички скриптове"),
                     ("openpyxl", "нужен само за Excel отчета на вариациите")):
        try:
            __import__(mod)
        except ImportError:
            missing.append((mod, why))

    if not missing:
        return OK, "requests и openpyxl са налични."
    hard = [m for m, _ in missing if m == "requests"]
    text = "Липсва: " + ", ".join(f"{m} ({why})" for m, why in missing)
    text += "\nИнсталирай с:  pip install " + " ".join(m for m, _ in missing)
    return (FAIL if hard else WARN), text


# ══════════════════════════════════════════════════════════════════════
#  2. Файлове
# ══════════════════════════════════════════════════════════════════════
def check_files(ctx):
    d = ctx.get("scripts_dir") or ""
    if not d or not os.path.isdir(d):
        return FAIL, f"Папката не съществува: {d}"

    missing = [s.file for s in screg.SCRIPTS
               if not os.path.isfile(os.path.join(d, s.file))]
    runtime_ok = os.path.isfile(os.path.join(d, "runtime.py"))

    if not runtime_ok:
        return FAIL, ("Липсва runtime.py — без него нито един скрипт няма да "
                      "тръгне. Разархивирай пакета наново.")
    if missing:
        return WARN, "Липсват скриптове: " + ", ".join(missing)
    return OK, f"Всички {len(screg.SCRIPTS)} скрипта и runtime.py са налице."


# ══════════════════════════════════════════════════════════════════════
#  3. EasyRea
# ══════════════════════════════════════════════════════════════════════
def check_easyrea(ctx, http=None):
    login = ctx.get("EASYREA_LOGIN", "").strip()
    pwd = ctx.get("EASYREA_PASSWORD", "").strip()
    if not login or not pwd:
        return SKIP, "Не са попълнени вход и парола."

    http = http or _requests()
    if http is None:
        return SKIP, "Липсва пакетът requests."

    try:
        s = http.Session()
        s.headers.update({
            "User-Agent": UA,
            "Origin": "https://easyrea.com",
            "Referer": "https://easyrea.com/",
            "Accept": "application/json, text/plain, */*",
        })
        s.get("https://easyrea.com/", timeout=TIMEOUT)
        r = s.post(f"{EASYREA_BASE}/user/login",
                   data={"login": login, "password": pwd},
                   headers={"Content-Type": "application/x-www-form-urlencoded"},
                   timeout=TIMEOUT)

        if r.status_code == 403:
            return FAIL, ("HTTP 403 — блокирано от anti-bot защитата (Incapsula). "
                          "Изчакай малко и пробвай пак.")
        if r.status_code != 200:
            return FAIL, f"Логинът върна HTTP {r.status_code}. Провери входа и паролата."

        xsrf = s.cookies.get("xsrf-token")
        if not xsrf:
            tok = s.cookies.get("token", "")
            if tok:
                try:
                    p = tok.split(".")[1]
                    p += "=" * (-len(p) % 4)
                    xsrf = json.loads(base64.urlsafe_b64decode(p)).get("xsrfToken")
                except (ValueError, IndexError):
                    xsrf = None
        if not xsrf:
            return FAIL, "Логинът мина, но не се получи xsrf токен."

        return OK, f"Логин успешен като „{login}“."
    except Exception as e:                                       # noqa: BLE001
        return FAIL, f"{type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════════════════
#  4. Shopify
# ══════════════════════════════════════════════════════════════════════
def check_shopify(ctx, http=None):
    store = ctx.get("SHOPIFY_STORE", "").strip()
    cid = ctx.get("SHOPIFY_CLIENT_ID", "").strip()
    secret = ctx.get("SHOPIFY_CLIENT_SECRET", "").strip()
    loc = ctx.get("SHOPIFY_LOCATION_ID", "").strip()

    if not store or not cid or not secret:
        return SKIP, "Не са попълнени магазин, Client ID или Secret."

    http = http or _requests()
    if http is None:
        return SKIP, "Липсва пакетът requests."

    try:
        r = http.post(f"https://{store}/admin/oauth/access_token",
                      json={"grant_type": "client_credentials",
                            "client_id": cid, "client_secret": secret},
                      timeout=TIMEOUT)
        if r.status_code != 200:
            return FAIL, (f"Токенът не се получи (HTTP {r.status_code}). "
                          "Провери Client ID / Secret и името на магазина.")
        token = (r.json() or {}).get("access_token")
        if not token:
            return FAIL, "Отговорът не съдържа access_token."

        q = """{ shop { name myshopifyDomain }
                 locations(first: 25) { nodes { id name } } }"""
        g = http.post(f"https://{store}/admin/api/{SHOPIFY_API_VER}/graphql.json",
                      headers={"X-Shopify-Access-Token": token,
                               "Content-Type": "application/json"},
                      json={"query": q}, timeout=TIMEOUT)
        if g.status_code != 200:
            return FAIL, f"GraphQL върна HTTP {g.status_code}."

        data = g.json()
        if "errors" in data:
            return FAIL, f"GraphQL грешка: {str(data['errors'])[:200]}"

        d = data.get("data") or {}
        shop = (d.get("shop") or {}).get("name", "?")
        nodes = ((d.get("locations") or {}).get("nodes")) or []
        names = {n["id"]: n.get("name", "") for n in nodes}

        if not loc:
            listing = "\n".join(f"    {i}  —  {n}" for i, n in names.items())
            return WARN, (f"Магазин „{shop}“ — връзката е наред, но Location ID "
                          f"не е попълнен.\nНалични локации:\n{listing}")

        if loc not in names:
            listing = "\n".join(f"    {i}  —  {n}" for i, n in names.items())
            return FAIL, (f"Магазин „{shop}“, но зададеният Location ID НЕ "
                          f"съществува:\n    {loc}\nНалични локации:\n{listing}")

        return OK, f"Магазин „{shop}“ · локация „{names[loc]}“ · токенът работи."
    except Exception as e:                                       # noqa: BLE001
        return FAIL, f"{type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════════════════
#  5. Anthropic
# ══════════════════════════════════════════════════════════════════════
def check_anthropic(ctx, http=None):
    key = ctx.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return SKIP, "Няма ключ (нужен само за качване на нови продукти)."

    http = http or _requests()
    if http is None:
        return SKIP, "Липсва пакетът requests."

    try:
        r = http.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": key,
                               "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": "claude-sonnet-4-6", "max_tokens": 1,
                            "messages": [{"role": "user", "content": "hi"}]},
                      timeout=TIMEOUT)
        if r.status_code == 200:
            return OK, "Ключът работи."
        if r.status_code == 401:
            return FAIL, "Невалиден ключ (401). Създай нов в console.anthropic.com."
        if r.status_code == 400:
            body = r.text[:200]
            if "model" in body.lower():
                return WARN, f"Ключът е валиден, но има проблем с модела: {body}"
            return WARN, f"HTTP 400: {body}"
        if r.status_code == 429:
            return WARN, "Ключът е валиден, но в момента има лимит (429)."
        return FAIL, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:                                       # noqa: BLE001
        return FAIL, f"{type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════════════════
#  Изпълнение
# ══════════════════════════════════════════════════════════════════════
CHECKS = [
    ("packages", "Python пакети", check_packages),
    ("files", "Файлове в папката", check_files),
    ("easyrea", "EasyRea", check_easyrea),
    ("shopify", "Shopify", check_shopify),
    ("anthropic", "Anthropic (Claude)", check_anthropic),
]


def run_all(ctx, on_result=None, http=None):
    """
    Изпълнява проверките една по една. on_result(id, статус, съобщение)
    се вика след всяка, за да може интерфейсът да ги показва постепенно.
    Връща {id: (статус, съобщение)}.
    """
    out = {}
    for cid, _label, fn in CHECKS:
        try:
            if fn in (check_packages, check_files):
                status, msg = fn(ctx)
            else:
                status, msg = fn(ctx, http=http)
        except Exception as e:                                   # noqa: BLE001
            status, msg = FAIL, f"{type(e).__name__}: {e}"
        out[cid] = (status, msg)
        if on_result:
            on_result(cid, status, msg)
    return out


def verdict(results):
    """Обща оценка: (статус, кратък текст)."""
    statuses = [s for s, _ in results.values()]
    n_fail = statuses.count(FAIL)
    n_skip = statuses.count(SKIP)

    if n_fail:
        word = "проверка не мина" if n_fail == 1 else "проверки не минаха"
        return FAIL, f"{n_fail} {word} — задачите ще гръмнат."

    if WARN in statuses:
        return WARN, "Всичко основно работи, но има какво да се дооправи."

    if n_skip:
        word = "проверка е пропусната" if n_skip == 1 else "проверки са пропуснати"
        return SKIP, (f"Провереното е наред, но {n_skip} {word} — "
                      "липсват данни за достъп.")

    return OK, "Всичко е наред."


def _requests():
    try:
        import requests
        return requests
    except ImportError:
        return None
