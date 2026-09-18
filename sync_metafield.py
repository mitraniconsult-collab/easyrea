#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронизира само metafield 'custom.expected_arrival' между easyrea и Shopify.

Логика:
  idTypeDispo=2 (In arrival) -> записва дата в metafield
  idTypeDispo=1 (In stock)   -> изтрива metafield ако има такъв
  Липсва в easyrea           -> не пипа metafield

Стартира се от приложението (app.py) или ръчно, след като креденшълите
са зададени като environment променливи:

  python3 sync_metafield.py --dry-run    (тест — нищо не се променя)
  python3 sync_metafield.py --real-run   (реален запис)

Тайните НЕ стоят в този файл. Виж runtime.py.
"""

import os, sys, time, json, datetime, requests

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
PAGE_SIZE             = 200
META_NAMESPACE        = "custom"
META_KEY              = "expected_arrival"

# ── Режим: идва от приложението (DRY_RUN / --dry-run / --real-run) ──────────
#    По подразбиране ТЕСТ. Виж runtime.py.
DRY_RUN = runtime.dry_run(default=True)

REPORT = f"metafield_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ── EasyRea ──────────────────────────────────────────────────────────────────
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


def easyrea_fetch(s, xsrf):
    """Връща dict: code -> {idTypeDispo, dateArrivage}"""
    url = f"{EASYREA_BASE}/magasins/{CODE_MAGASIN}/{SUFFIXE_MAGASIN}/produits"
    out = {}
    page, total = 1, None
    while True:
        body = {
            "idsSegmentation": [], "idsTheme": [], "codesGroupes": [], "idsFavori": [],
            "idsPictogrammes": [], "idsPicto": [], "idsUsine": [], "codesMarque": [],
            "codesStyle": [], "inPanier": [], "typesMassif": [], "idsFonctionAffiner": [],
            "tradepalDestockagePourcentRemise": [], "idProgrammeEtp": None,
            "idCleContainer": None, "idsCleContainer": [], "idsTypeDispo": [],
            "checkIsStateCentrale2": False, "incoterm": [],
            "nombreAffichage": PAGE_SIZE, "page": page, "texte": "",
            "tousProduits": True, "ordreAffichage": "ORDER_CATEGORIE_ASC",
            "isRayon": False, "isAllRayon": False,
            "codeMagasin": CODE_MAGASIN, "suffixeMagasin": SUFFIXE_MAGASIN,
            "modeMultiMag": False, "typePanier": "STD",
        }
        r = s.post(url, json=body, timeout=60, headers={
            "Content-Type": "application/json;charset=UTF-8",
            "x-csrf-token": xsrf, "lang": "en",
            "Referer": "https://easyrea.com/produits/tous",
        })
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if total is None:
            total = data.get("totalResults", 0)
            print(f"[easyrea] Общо: {total}")
        if not results:
            break
        for p in results:
            code = str(p.get("codeArticle", "")).strip()
            if code and code not in out:
                out[code] = {
                    "idTypeDispo": p.get("idTypeDispo"),
                    "dateArrivage": p.get("dateArrivageADateJour"),
                    "libelle": p.get("libelle", ""),
                }
        print(f"[easyrea] стр.{page} → {len(out)}")
        page += 1
        if total and (page - 1) * PAGE_SIZE >= total:
            break
        time.sleep(0.3)
    print(f"[easyrea] Готово: {len(out)} кода")
    return out


# ── Shopify ──────────────────────────────────────────────────────────────────
def shopify_token():
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
        json={"grant_type": "client_credentials",
              "client_id": SHOPIFY_CLIENT_ID,
              "client_secret": SHOPIFY_CLIENT_SECRET}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"[shopify] Токен OK")
    return token


def gql(token, query, variables=None, attempts=4):
    """
    GraphQL заявка с повторен опит при ВРЕМЕННИ грешки.

    503/502/500 и 429 (лимит) са преходни — Shopify просто е зает. Преди
    един такъв отговор губеше продукта за целия цикъл. Сега се изчаква
    нарастващо време и се пробва пак. Грешките в самата заявка (400, или
    "errors" в отговора) НЕ се повтарят — те няма да се оправят сами.
    """
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VER}/graphql.json"
    last = None

    for attempt in range(1, attempts + 1):
        try:
            r = requests.post(
                url,
                headers={"X-Shopify-Access-Token": token,
                         "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}}, timeout=60)

            if r.status_code in (429, 500, 502, 503, 504):
                last = requests.HTTPError(
                    f"{r.status_code} {r.reason} for url: {url}", response=r)
                if attempt < attempts:
                    wait = min(2 ** attempt, 16)
                    print(f"      [изчаквам] HTTP {r.status_code}, опит "
                          f"{attempt}/{attempts} — пауза {wait} сек", flush=True)
                    time.sleep(wait)
                    continue
                raise last

            r.raise_for_status()
            data = r.json()
            if "errors" in data:
                raise RuntimeError(f"GQL error: {data['errors']}")

            # throttle
            avail = data.get("extensions", {}).get("cost", {}).get(
                "throttleStatus", {}).get("currentlyAvailable", 1000)
            if avail < 200:
                time.sleep(2)
            return data["data"]

        except requests.exceptions.RequestException as e:
            # мрежов проблем (прекъсване, таймаут) — също си струва повторен опит
            last = e
            if attempt < attempts:
                wait = min(2 ** attempt, 16)
                print(f"      [изчаквам] {type(e).__name__}, опит "
                      f"{attempt}/{attempts} — пауза {wait} сек", flush=True)
                time.sleep(wait)
                continue
            raise

    raise last if last else RuntimeError("gql: неуспех без причина")


def shopify_fetch_variants(token):
    """Връща list of {sku, product_id, metafield_id, current_date}"""
    out = []
    cursor = None
    q = """
    query($c: String) {
      productVariants(first: 200, after: $c) {
        pageInfo { hasNextPage endCursor }
        nodes {
          sku
          product {
            id
            vendor
            metafield(namespace: "custom", key: "expected_arrival") {
              id
              value
            }
          }
        }
      }
    }"""
    while True:
        d = gql(token, q, {"c": cursor})
        conn = d["productVariants"]
        seen = set()  # един продукт може да има много варианти — пипаме go веднъж
        for n in conn["nodes"]:
            sku = (n.get("sku") or "").strip()
            if not sku:
                continue
            prod = n["product"]
            pid = prod["id"]
            if pid in seen:
                continue
            seen.add(pid)
            mf = prod.get("metafield")
            out.append({
                "sku": sku,
                "product_id": pid,
                "vendor": (prod.get("vendor") or "").strip().lower(),
                "metafield_id": mf["id"] if mf else None,
                "current_date": mf["value"] if mf else None,
            })
        if conn["pageInfo"]["hasNextPage"]:
            cursor = conn["pageInfo"]["endCursor"]
            print(f"[shopify] заредени: {len(out)}")
        else:
            break
    print(f"[shopify] Общо уникални продукта: {len(out)}")
    return out


def set_metafield(token, product_id, date_str):
    q = """
    mutation($m: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $m) {
        metafields { id }
        userErrors { field message }
      }
    }"""
    data = gql(token, q, {"m": [{
        "ownerId": product_id,
        "namespace": META_NAMESPACE,
        "key": META_KEY,
        "type": "date",
        "value": date_str,
    }]})

    # Без тази проверка неуспешен запис се отчиташе като успешен.
    errs = ((data or {}).get("metafieldsSet") or {}).get("userErrors") or []
    if errs:
        raise RuntimeError(f"metafieldsSet userErrors: {errs}")
    return data


def delete_metafield(token, product_id):
    """
    Изтрива custom.expected_arrival от продукт.

    ВАЖНО: старата мутация metafieldDelete(input: {id}) беше премахната от
    Shopify в API версия 2025-01. Заместникът metafieldsDelete работи не с
    ID на metafield-а, а с тройката (ownerId, namespace, key).
    Ако metafield-ът не съществува, мутацията пак минава успешно.
    """
    q = """
    mutation($m: [MetafieldIdentifierInput!]!) {
      metafieldsDelete(metafields: $m) {
        deletedMetafields { ownerId namespace key }
        userErrors { field message }
      }
    }"""
    data = gql(token, q, {"m": [{
        "ownerId": product_id,
        "namespace": META_NAMESPACE,
        "key": META_KEY,
    }]})

    errs = ((data or {}).get("metafieldsDelete") or {}).get("userErrors") or []
    if errs:
        raise RuntimeError(f"metafieldsDelete userErrors: {errs}")
    return data


# ── ГЛАВНА ФУНКЦИЯ ────────────────────────────────────────────────────────────
def main():
    runtime.print_mode_banner("EasyRea → Shopify · дати за пристигане", DRY_RUN)

    s, xsrf = easyrea_login()
    easyrea = easyrea_fetch(s, xsrf)

    token = shopify_token()
    variants = shopify_fetch_variants(token)

    import csv
    stats = {"SET": 0, "DELETE": 0, "SKIP": 0, "NO_MATCH": 0, "ERROR": 0}
    rows = []

    _total = len(variants)
    for _i, v in enumerate(variants, 1):
        if _i % 200 == 0 or _i == _total:
            print(f"PROGRESS {_i}/{_total}", flush=True)
        sku = v["sku"]
        rec = easyrea.get(sku)

        if rec is None:
            # Не е в easyrea — не пипаме metafield
            stats["NO_MATCH"] += 1
            continue

        disp = rec["idTypeDispo"]
        date = rec["dateArrivage"]
        action = ""
        note = ""

        if disp == 2 and date:
            # In arrival — трябва да има дата
            if v["current_date"] == date:
                action = "SKIP"
                note = f"Датата вече е {date}"
                stats["SKIP"] += 1
            else:
                action = "SET"
                note = f"{v['current_date'] or 'няма'} → {date}"
                stats["SET"] += 1
                if not DRY_RUN:
                    try:
                        set_metafield(token, v["product_id"], date)
                    except Exception as e:
                        action = "ERROR"
                        note = str(e)
                        stats["ERROR"] += 1
                        stats["SET"] -= 1

        elif disp == 1 and v["metafield_id"]:
            # In stock — изтрий датата ако има
            action = "DELETE"
            note = f"Беше: {v['current_date']}"
            stats["DELETE"] += 1
            if not DRY_RUN:
                try:
                    delete_metafield(token, v["product_id"])
                except Exception as e:
                    action = "ERROR"
                    note = str(e)
                    stats["ERROR"] += 1
                    stats["DELETE"] -= 1
        else:
            action = "SKIP"
            note = "Нищо за правене"
            stats["SKIP"] += 1

        rows.append({
            "sku": sku,
            "product_id": v["product_id"],
            "libelle": rec["libelle"],
            "action": action,
            "note": note,
        })

    # Отчет
    if rows:
        with open(REPORT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["sku","product_id","libelle","action","note"])
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
