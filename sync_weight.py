#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Еднократна масова синхронизация на теглото от easyrea към Shopify.

За всеки Shopify вариант (по SKU):
  1. Вика /fiche-produit/{sku} в easyrea
  2. Взима poidsProduit (напр. "0.330 Kg")
  3. Конвертира в грамове (330)
  4. Записва в Shopify variant weight поле

Режимът се управлява от приложението (или --dry-run / --real-run).
По подразбиране е ТЕСТ — само показва какво ще се промени.

Очаквано време: ~75 мин за 9000 продукта
"""

import os, re, sys, time, json, datetime, csv, requests

import runtime

# ── Credentials ─────────────────────────────────────────────────────────────
_CREDS = runtime.require_env(
    "EASYREA_LOGIN", "EASYREA_PASSWORD",
    "SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
)
EASYREA_LOGIN         = _CREDS["EASYREA_LOGIN"]
EASYREA_PASSWORD      = _CREDS["EASYREA_PASSWORD"]
SHOPIFY_STORE         = _CREDS["SHOPIFY_STORE"]
SHOPIFY_CLIENT_ID     = _CREDS["SHOPIFY_CLIENT_ID"]
SHOPIFY_CLIENT_SECRET = _CREDS["SHOPIFY_CLIENT_SECRET"]
SHOPIFY_API_VER       = "2026-04"
CODE_MAGASIN          = "26284"
SUFFIXE_MAGASIN       = "1"
EASYREA_BASE          = "https://api-prod.easyrea.com/private/api/easyrea"

# Режим: идва от приложението (DRY_RUN / --dry-run / --real-run).
DRY_RUN = runtime.dry_run(default=True)

REPORT = f"weight_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ── EasyRea логин ────────────────────────────────────────────────────────────
def easyrea_login():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Origin": "https://easyrea.com", "Referer": "https://easyrea.com/",
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site",
    })
    s.get("https://easyrea.com/", timeout=30)
    r = s.post(f"{EASYREA_BASE}/user/login",
               data={"login": EASYREA_LOGIN, "password": EASYREA_PASSWORD},
               headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    if r.status_code != 200:
        print(f"[диагностика] login={repr(EASYREA_LOGIN)} password_len={len(EASYREA_PASSWORD)} password_first2={repr(EASYREA_PASSWORD[:2])} password_last2={repr(EASYREA_PASSWORD[-2:])}")
        raise RuntimeError(f"Логин неуспешен: {r.status_code} {r.text[:200]}")
    xsrf = s.cookies.get("xsrf-token")
    if not xsrf:
        import base64
        tok = s.cookies.get("token", "")
        if tok:
            p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
            xsrf = json.loads(base64.urlsafe_b64decode(p)).get("xsrfToken")
    print(f"[easyrea] Логин OK")
    return s, xsrf


def easyrea_get_weight(s, xsrf, sku, retries=3):
    """Взима poidsProduit от /fiche-produit/{sku}. Връща грамове или None."""
    url = f"{EASYREA_BASE}/magasins/{CODE_MAGASIN}/{SUFFIXE_MAGASIN}/fiche-produit/{sku}"
    for attempt in range(retries):
        try:
            r = s.post(url, json={}, timeout=30, headers={
                "Content-Type": "application/json;charset=UTF-8",
                "x-csrf-token": xsrf,
                "lang": "en",
                "Referer": f"https://easyrea.com/produits/{sku}",
            })
            if r.status_code == 404:
                return None  # продуктът не съществува
            r.raise_for_status()
            data = r.json()
            # poidsProduit е в informationsTechniques
            tech = data.get("informationsTechniques") or {}
            poids = tech.get("poidsProduit") or ""
            if not poids:
                return None
            # Парсвай "0.330 Kg" или "1.2 kg" или "330g"
            match = re.search(r'([\d.,]+)\s*(kg|g)', poids.lower())
            if not match:
                return None
            value = float(match.group(1).replace(',', '.'))
            unit = match.group(2)
            grams = int(value * 1000) if unit == 'kg' else int(value)
            return grams
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout):
            if attempt < retries - 1:
                time.sleep((attempt + 1) * 2)
            else:
                return None
    return None


# ── Shopify ──────────────────────────────────────────────────────────────────
_shopify_session = None

def get_shopify_session():
    global _shopify_session
    if _shopify_session is None:
        _shopify_session = requests.Session()
        _shopify_session.headers.update({"Content-Type": "application/json"})
    return _shopify_session


def shopify_token():
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
        json={"grant_type": "client_credentials",
              "client_id": SHOPIFY_CLIENT_ID,
              "client_secret": SHOPIFY_CLIENT_SECRET}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    get_shopify_session().headers["X-Shopify-Access-Token"] = token
    print(f"[shopify] Токен OK")
    return token


def gql(token, query, variables=None, retries=5):
    global _shopify_session
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VER}/graphql.json"
    for attempt in range(retries):
        try:
            s = get_shopify_session()
            r = s.post(url, json={"query": query, "variables": variables or {}}, timeout=90)
            r.raise_for_status()
            data = r.json()
            if "errors" in data:
                raise RuntimeError(f"GQL error: {data['errors']}")
            avail = data.get("extensions", {}).get("cost", {}).get(
                "throttleStatus", {}).get("currentlyAvailable", 1000)
            if avail < 200:
                time.sleep(2)
            return data["data"]
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            wait = (attempt + 1) * 5
            print(f"  [retry {attempt+1}/{retries}] {type(e).__name__}. Изчаквам {wait}с...")
            time.sleep(wait)
            _shopify_session = None
            get_shopify_session().headers["X-Shopify-Access-Token"] = token
    raise RuntimeError(f"Неуспешно след {retries} опита")


def shopify_fetch_variants(token):
    """Взима всички варианти с текущо тегло."""
    out = []
    cursor = None
    q = """
    query($c: String) {
      productVariants(first: 200, after: $c) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          sku
          inventoryItem {
            id
            measurement {
              weight {
                value
                unit
              }
            }
          }
          product { id title vendor }
        }
      }
    }"""
    while True:
        d = gql(token, q, {"c": cursor})
        conn = d["productVariants"]
        for n in conn["nodes"]:
            sku = (n.get("sku") or "").strip()
            if not sku:
                continue
            # Извлечи текущото тегло от inventoryItem.measurement.weight
            inv = n.get("inventoryItem") or {}
            meas = inv.get("measurement") or {}
            w = meas.get("weight") or {}
            current_val = w.get("value") or 0
            current_unit = w.get("unit", "GRAMS")
            # Конвертирай в грамове
            if current_unit == "KILOGRAMS":
                current_g = int(float(current_val) * 1000)
            else:
                current_g = int(float(current_val))
            out.append({
                "sku": sku,
                "variant_id": n["id"],
                "inventory_item_id": inv.get("id"),
                "product_id": n["product"]["id"],
                "title": n["product"].get("title", ""),
                "vendor": (n["product"].get("vendor") or "").lower(),
                "current_weight_g": current_g,
            })
        if conn["pageInfo"]["hasNextPage"]:
            cursor = conn["pageInfo"]["endCursor"]
            print(f"[shopify] заредени варианти: {len(out)}")
        else:
            break
    print(f"[shopify] Общо: {len(out)}")
    return out


def set_weight(token, inventory_item_id, grams):
    """Записва тегло в грамове чрез inventoryItemUpdate."""
    q = """
    mutation($id: ID!, $input: InventoryItemInput!) {
      inventoryItemUpdate(id: $id, input: $input) {
        inventoryItem {
          id
          measurement { weight { value unit } }
        }
        userErrors { field message }
      }
    }"""
    gql(token, q, {
        "id": inventory_item_id,
        "input": {
            "measurement": {
                "weight": {
                    "value": grams,
                    "unit": "GRAMS",
                }
            }
        }
    })


# ── EASYREA VENDOR FILTER ────────────────────────────────────────────────────
EASYREA_VENDORS = {"atmosphera", "hesperide", "5five", "secret de gourmet", "feeric"}


# ── ГЛАВНА ФУНКЦИЯ ────────────────────────────────────────────────────────────
def main():
    runtime.print_mode_banner("EasyRea → Shopify · тегло", DRY_RUN)

    s, xsrf = easyrea_login()
    token = shopify_token()
    variants = shopify_fetch_variants(token)

    # Филтрирай само easyrea брандове
    easyrea_variants = [v for v in variants if v["vendor"] in EASYREA_VENDORS]
    print(f"\n[филтър] easyrea варианти: {len(easyrea_variants)} / {len(variants)} общо")

    stats = {"SET": 0, "SKIP": 0, "NO_WEIGHT": 0, "ERROR": 0}
    rows = []
    total = len(easyrea_variants)

    for i, v in enumerate(easyrea_variants, 1):
        sku = v["sku"]

        # Взими тегло от easyrea
        grams = easyrea_get_weight(s, xsrf, sku)
        time.sleep(0.4)  # учтиво към easyrea

        if grams is None:
            stats["NO_WEIGHT"] += 1
            rows.append({"sku": sku, "title": v["title"][:40],
                         "action": "NO_WEIGHT", "note": "Няма тегло в easyrea"})
            continue

        current = v["current_weight_g"]

        if current == grams:
            stats["SKIP"] += 1
            continue  # вече е правилното тегло

        action = "SET"
        note = f"{current}g → {grams}g"
        stats["SET"] += 1

        if not DRY_RUN:
            try:
                set_weight(token, v["inventory_item_id"], grams)
                time.sleep(0.3)
            except Exception as e:
                action = "ERROR"
                note = str(e)[:80]
                stats["ERROR"] += 1
                stats["SET"] -= 1

        rows.append({"sku": sku, "title": v["title"][:40], "action": action, "note": note})

        # Прогрес всеки 100
        if i % 100 == 0:
            print(f"  [{i}/{total}] SET:{stats['SET']} SKIP:{stats['SKIP']} "
                  f"NO_WEIGHT:{stats['NO_WEIGHT']} ERROR:{stats['ERROR']}")

    # Отчет
    if rows:
        with open(REPORT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["sku", "title", "action", "note"])
            w.writeheader()
            w.writerows(rows)

    print(f"\n=== ОБОБЩЕНИЕ ===")
    for k, n in stats.items():
        if n:
            print(f"  {k}: {n}")
    print(f"\nОтчет: {REPORT}")
    if DRY_RUN:
        print(">>> ТЕСТ (DRY RUN) — нищо не е променено.")
        print(">>> За реален запис изключи DRY RUN в приложението")
        print(">>> или пусни скрипта с --real-run.")
    else:
        print(">>> РЕАЛЕН режим — промените са приложени.")


if __name__ == "__main__":
    main()
