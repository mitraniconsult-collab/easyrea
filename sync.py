#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyRea -> Shopify наличност / синхронизация
=============================================

Какво прави:
  1. Логва се в easyrea (cookie + xsrf-token сесия).
  2. Изтегля ВСИЧКИ продукти (всичките ~20500) от /produits с пагинация.
  3. Изтегля всички варианти от Shopify (по SKU) през GraphQL Admin API.
  4. Сравнява по код (codeArticle == Shopify SKU) и решава за всеки:
        - В наличност (idTypeDispo=1, qteDispo>0)  -> наличност в Shopify
        - На път      (idTypeDispo=2)              -> наличност 0 + metafield дата
        - Липсва в easyrea изцяло                  -> продуктът -> DRAFT
  5. РЕЖИМ "DRY RUN" (по подразбиране): нищо не променя, само пише отчет CSV.
     Когато си готов: сложи DRY_RUN = False, за да прилага реалните промени.

ВАЖНО за сигурност:
  - Не дръж паролите в кода. Чети ги от environment променливи.
  - Смени паролата на easyrea (беше споделена при настройката).

Изисквания:
    pip install requests
"""

import os
import csv
import sys
import time
import json
import datetime
import requests

import runtime

# ============================================================
#  НАСТРОЙКИ
# ============================================================

# ---- Режим: идва от приложението (DRY_RUN / --dry-run / --real-run).
#      По подразбиране ТЕСТ. Виж runtime.py. ----
DRY_RUN = runtime.dry_run(default=True)

# ---- Предпазна спирачка ----
# Ако делът на продуктите, които биха отишли в MISSING (наличност 0),
# надхвърли този процент, скриптът СПИРА, без да пипа нищо. Пази те от
# ситуация, в която easyrea върне непълен отговор и целият магазин
# се обезличи. Изключва се с --force.
MAX_MISSING_PCT = 25.0

# ---- EasyRea ----
EASYREA_BASE      = "https://api-prod.easyrea.com/private/api/easyrea"
_CREDS = runtime.require_env(
    "EASYREA_LOGIN", "EASYREA_PASSWORD",
    "SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
    "SHOPIFY_LOCATION_ID",
)
EASYREA_LOGIN     = _CREDS["EASYREA_LOGIN"]
EASYREA_PASSWORD  = _CREDS["EASYREA_PASSWORD"]
CODE_MAGASIN      = "26284"
SUFFIXE_MAGASIN   = "1"
PAGE_SIZE         = 200          # колко продукта на страница (вдигнато за по-малко заявки)

# ---- Shopify ----
# Токенът се взима АВТОМАТИЧНО от Client ID + Secret (client credentials grant).
# Не пишеш токен ръчно — скриптът си го взима свеж при всяко пускане.
SHOPIFY_STORE         = _CREDS["SHOPIFY_STORE"]
SHOPIFY_CLIENT_ID     = _CREDS["SHOPIFY_CLIENT_ID"]
SHOPIFY_CLIENT_SECRET = _CREDS["SHOPIFY_CLIENT_SECRET"]
SHOPIFY_API_VER   = "2026-04"
SHOPIFY_LOCATION_ID   = _CREDS["SHOPIFY_LOCATION_ID"]

# Metafield за датата на пристигане ("на път" продукти)
META_NAMESPACE    = "custom"
META_KEY          = "expected_arrival"

# Колко наличност да слагаме за наличните продукти.
# easyrea дава реални огромни количества (qteDispo). За дропшипинг логика
# обикновено е по-разумно фиксирано число, вместо реалния склад на доставчика.
IN_STOCK_QTY      = 100

# Третиране на "безкрайния" placeholder на easyrea
INFINITE_QTY      = 2147483647   # easyrea връща това като "неограничено"

# ВАЖНО: само продукти с тези vendor-и се пипат. Всичко друго (други
# доставчици) се ПРОПУСКА напълно — нито наличност, нито DRAFT.
# Сравнението е без значение за главни/малки букви и интервали.
EASYREA_VENDORS = {
    "atmosphera",
    "hesperide",
    "5five",
    "secret de gourmet",
    "feeric",
}

REPORT_FILE = "sync_report_{}.csv".format(
    datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
)

# ============================================================
#  EASYREA
# ============================================================

class EasyRea:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/148.0.0.0 Safari/537.36",
            "Origin": "https://easyrea.com",
            "Referer": "https://easyrea.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,bg;q=0.8",
            "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        })
        self.xsrf = None

    def login(self):
        # Стъпка 0: посети easyrea.com, за да вземеш Incapsula cookies
        # (без това login-ът връща 403). Това е същото, което правеше diag.py.
        try:
            self.s.get("https://easyrea.com/", timeout=30)
        except Exception:
            pass

        url = f"{EASYREA_BASE}/user/login"
        r = self.s.post(
            url,
            data={"login": EASYREA_LOGIN, "password": EASYREA_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[easyrea] Логин неуспешен. HTTP {r.status_code}")
            print(f"[easyrea] Content-Type: {r.headers.get('Content-Type')}")
            print(f"[easyrea] Отговор (първи 400 символа):\n{r.text[:400]}")
            print(f"[easyrea] EASYREA_LOGIN, който се ползва: '{EASYREA_LOGIN}'")
            pw = EASYREA_PASSWORD
            masked = (pw[:2] + "***" + pw[-1:]) if len(pw) > 3 else "(празна/къса)"
            print(f"[easyrea] Парола (маскирана): {masked}  (дължина={len(pw)})")
            r.raise_for_status()
        # xsrf токенът идва като cookie 'xsrf-token' (= x-csrf-token header).
        self.xsrf = self.s.cookies.get("xsrf-token")
        if not self.xsrf:
            # резервен вариант: разкодирай го от JWT 'token' cookie
            tok = self.s.cookies.get("token")
            if tok:
                import base64
                payload = tok.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload))
                self.xsrf = data.get("xsrfToken")
        if not self.xsrf:
            raise RuntimeError("Логинът успя, но xsrf токенът не е намерен.")
        print(f"[easyrea] Логин успешен. xsrf={self.xsrf[:8]}...")

    def fetch_all_products(self):
        """Връща dict: code(str) -> {idTypeDispo, qteDispo, dateArrivage, libelle}"""
        url = f"{EASYREA_BASE}/magasins/{CODE_MAGASIN}/{SUFFIXE_MAGASIN}/produits"
        out = {}
        page = 1
        total = None
        while True:
            body = {
                "idsSegmentation": [], "idsTheme": [], "codesGroupes": [],
                "idsFavori": [], "idsPictogrammes": [], "idsPicto": [],
                "idsUsine": [], "codesMarque": [], "codesStyle": [],
                "inPanier": [], "typesMassif": [], "idsFonctionAffiner": [],
                "tradepalDestockagePourcentRemise": [], "idProgrammeEtp": None,
                "idCleContainer": None, "idsCleContainer": [], "idsTypeDispo": [],
                "checkIsStateCentrale2": False, "incoterm": [],
                "nombreAffichage": PAGE_SIZE, "page": page, "texte": "",
                "tousProduits": True, "ordreAffichage": "ORDER_CATEGORIE_ASC",
                "isRayon": False, "isAllRayon": False,
                "codeMagasin": CODE_MAGASIN, "suffixeMagasin": SUFFIXE_MAGASIN,
                "modeMultiMag": False, "typePanier": "STD",
            }
            r = self.s.post(
                url, json=body, timeout=60,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "x-csrf-token": self.xsrf,
                    "lang": "en",
                    "Referer": "https://easyrea.com/produits/tous",
                },
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            if total is None:
                total = data.get("totalResults", 0)
                print(f"[easyrea] Общо продукти: {total}")
            if not results:
                break
            for p in results:
                code = str(p.get("codeArticle", "")).strip()
                if not code:
                    continue
                # ако код се повтаря (масификация), пазим "най-добрия" статус
                rec = {
                    "idTypeDispo": p.get("idTypeDispo"),
                    "qteDispo": p.get("qteDispo"),
                    "dateArrivage": p.get("dateArrivageADateJour"),
                    "libelle": p.get("libelle", ""),
                }
                if code not in out or rec["idTypeDispo"] == 1:
                    out[code] = rec
            print(f"[easyrea] страница {page}: +{len(results)} (общо уникални: {len(out)})")
            page += 1
            if total and (page - 1) * PAGE_SIZE >= total:
                break
            time.sleep(0.3)  # учтиво към сървъра / Incapsula
        print(f"[easyrea] Готово. Уникални кодове: {len(out)}")
        return out


# ============================================================
#  SHOPIFY
# ============================================================

class Shopify:
    def __init__(self):
        self.base = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VER}"
        token = self._get_token()
        self.headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }

    def _get_token(self):
        """Взима свеж Admin API токен чрез client credentials grant."""
        if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
            raise RuntimeError("Задай SHOPIFY_CLIENT_ID и SHOPIFY_CLIENT_SECRET.")
        r = requests.post(
            f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
            json={
                "grant_type": "client_credentials",
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
            },
            timeout=30,
        )
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            raise RuntimeError(f"Токенът не е получен: {r.text[:200]}")
        print(f"[shopify] Токен получен: {token[:12]}...")
        return token

    def gql(self, query, variables=None):
        r = requests.post(
            f"{self.base}/graphql.json",
            headers=self.headers,
            json={"query": query, "variables": variables or {}},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"Shopify GraphQL error: {data['errors']}")
        # throttle handling
        cost = data.get("extensions", {}).get("cost", {})
        avail = cost.get("throttleStatus", {}).get("currentlyAvailable", 1000)
        if avail < 200:
            time.sleep(2)
        return data["data"]

    def fetch_all_variants(self):
        """Връща списък от dict: {sku, variant_id, product_id, inventory_item_id, status}"""
        out = []
        cursor = None
        q = """
        query($cursor: String) {
          productVariants(first: 200, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              sku
              id
              inventoryPolicy
              inventoryItem { id }
              product { id status vendor templateSuffix }
            }
          }
        }"""
        while True:
            d = self.gql(q, {"cursor": cursor})
            conn = d["productVariants"]
            for n in conn["nodes"]:
                sku = (n.get("sku") or "").strip()
                if not sku:
                    continue
                out.append({
                    "sku": sku,
                    "variant_id": n["id"],
                    "product_id": n["product"]["id"],
                    "inventory_item_id": n["inventoryItem"]["id"],
                    "status": n["product"]["status"],
                    "vendor": (n["product"].get("vendor") or "").strip(),
                    "inventory_policy": n.get("inventoryPolicy", "DENY"),
                    "template_suffix": (n["product"].get("templateSuffix") or ""),
                })
            if conn["pageInfo"]["hasNextPage"]:
                cursor = conn["pageInfo"]["endCursor"]
                print(f"[shopify] заредени варианти: {len(out)}")
            else:
                break
        print(f"[shopify] Общо варианти със SKU: {len(out)}")
        return out

    # ---- мутации (използват се само ако DRY_RUN = False) ----

    def set_inventory(self, inventory_item_id, qty):
        q = """
        mutation($input: InventorySetQuantitiesInput!) {
          inventorySetQuantities(input: $input) {
            userErrors { field message }
          }
        }"""
        v = {"input": {
            "name": "available",
            "reason": "correction",
            "ignoreCompareQuantity": True,
            "quantities": [{
                "inventoryItemId": inventory_item_id,
                "locationId": SHOPIFY_LOCATION_ID,
                "quantity": int(qty),
            }],
        }}
        self.gql(q, v)

    def set_product_status(self, product_id, status):
        q = """
        mutation($input: ProductInput!) {
          productUpdate(input: $input) {
            userErrors { field message }
          }
        }"""
        self.gql(q, {"input": {"id": product_id, "status": status}})

    def set_metafield_date(self, product_id, date_str):
        q = """
        mutation($m: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $m) {
            userErrors { field message }
          }
        }"""
        v = {"m": [{
            "ownerId": product_id,
            "namespace": META_NAMESPACE,
            "key": META_KEY,
            "type": "date",
            "value": date_str,
        }]}
        self.gql(q, v)


    def set_variant_oversell(self, variant_id, allow):
        """inventoryPolicy: CONTINUE=продава при 0, DENY=спира при 0"""
        q = """
        mutation($input: ProductVariantInput!) {
          productVariantUpdate(input: $input) {
            userErrors { field message }
          }
        }"""
        self.gql(q, {"input": {
            "id": variant_id,
            "inventoryPolicy": "CONTINUE" if allow else "DENY",
        }})

    def set_template(self, product_id, template_suffix):
        """template_suffix: '' = default product, 'preorder' = preorder"""
        q = """
        mutation($input: ProductInput!) {
          productUpdate(input: $input) {
            userErrors { field message }
          }
        }"""
        self.gql(q, {"input": {
            "id": product_id,
            "templateSuffix": template_suffix,
        }})


# ============================================================
#  ЛОГИКА ЗА СИНХРОНИЗАЦИЯ
# ============================================================

def decide(rec):
    """
    Финална логика:
      IN_STOCK (idTypeDispo=1) -> не пипаме qty, Continue selling ON
      ARRIVING (idTypeDispo=2) -> не пипаме qty, Continue selling ON,
                                   template=preorder, metafield дата
      MISSING  (rec is None)   -> qty=0, Continue selling OFF
    """
    if rec is None:
        return ("MISSING", None, None, "Липсва в easyrea — qty=0, DENY")

    disp = rec["idTypeDispo"]

    if disp == 1:
        return ("IN_STOCK", None, None, "В наличност (qty не се пипа)")

    if disp == 2:
        return ("ARRIVING", None, rec["dateArrivage"], "На път — template=preorder + дата")

    return ("MISSING", None, None, f"Неизвестен idTypeDispo={disp}")


def main():
    runtime.print_mode_banner("EasyRea → Shopify · наличности", DRY_RUN)

    er = EasyRea()
    er.login()
    easyrea = er.fetch_all_products()

    sh = Shopify()
    variants = sh.fetch_all_variants()

    # ── СТЪПКА 1: реши какво трябва да стане, без да пипаш нищо ──────────
    plan = []
    skipped_other_vendor = 0
    for v in variants:
        # ЗАЩИТА: пипаме само продукти от easyrea брандовете.
        # Всичко от друг доставчик се пропуска напълно.
        if v.get("vendor", "").strip().lower() not in EASYREA_VENDORS:
            skipped_other_vendor += 1
            continue

        # Директно мачване по SKU — 166571 и 166571A са РАЗЛИЧНИ продукти
        # (различни цветове/варианти), затова НЕ правим fallback по базов код.
        rec = easyrea.get(v["sku"])
        action, qty, date, reason = decide(rec)
        plan.append((v, rec, action, date, reason))

    # ── СТЪПКА 2: предпазна спирачка ────────────────────────────────────
    n_total = len(plan)
    n_missing = sum(1 for p in plan if p[2] == "MISSING")
    pct = (n_missing / n_total * 100) if n_total else 0.0
    print(f"\n[план] {n_total} продукта от easyrea брандовете | "
          f"MISSING: {n_missing} ({pct:.1f}%)")

    if not DRY_RUN and n_total and pct > MAX_MISSING_PCT and not runtime.force():
        print("\n" + "!" * 70)
        print(f"СПИРАМ: {pct:.1f}% от продуктите биха отишли в MISSING "
              f"(праг: {MAX_MISSING_PCT}%).")
        print("Това обикновено значи непълен отговор от easyrea, а не реална")
        print("липса на стоки. НИЩО не е променено в Shopify.")
        print("Ако промяната наистина е очаквана, пусни отново с --force.")
        print("!" * 70)
        sys.exit(3)

    if n_total == 0:
        print("[внимание] Няма нито един продукт с vendor от списъка "
              f"{sorted(EASYREA_VENDORS)}. Провери vendor полетата в Shopify.")

    # ── СТЪПКА 3: приложи ───────────────────────────────────────────────
    rows = []
    for i, (v, rec, action, date, reason) in enumerate(plan, 1):
        if i % 100 == 0 or i == n_total:
            print(f"PROGRESS {i}/{n_total}", flush=True)
        sku = v["sku"]
        changed = ""
        if not DRY_RUN:
            try:
                if action == "IN_STOCK":
                    # Не пипаме наличността — само Continue selling ON
                    if v["inventory_policy"] != "CONTINUE":
                        sh.set_variant_oversell(v["variant_id"], allow=True)
                    # Ако е бил на preorder — върни към default template
                    if v["template_suffix"] == "preorder":
                        sh.set_template(v["product_id"], "")

                elif action == "ARRIVING":
                    # Не пипаме наличността — Continue selling ON
                    if v["inventory_policy"] != "CONTINUE":
                        sh.set_variant_oversell(v["variant_id"], allow=True)
                    # Template → preorder
                    if v["template_suffix"] != "preorder":
                        sh.set_template(v["product_id"], "preorder")
                    # Metafield дата
                    if date:
                        sh.set_metafield_date(v["product_id"], date)

                elif action == "MISSING":
                    # Наличност → 0
                    sh.set_inventory(v["inventory_item_id"], 0)
                    # Continue selling → OFF
                    if v["inventory_policy"] != "DENY":
                        sh.set_variant_oversell(v["variant_id"], allow=False)

                changed = "applied"
            except Exception as e:
                changed = f"ERROR: {e}"

        rows.append({
            "sku": sku,
            "libelle": rec["libelle"] if rec else "",
            "action": action,
            "arrival_date": date or "",
            "shopify_status": v["status"],
            "current_template": v["template_suffix"] or "default",
            "current_oversell": v["inventory_policy"],
            "reason": reason,
            "applied": changed,
        })

    # отчет
    FIELDS = ["sku", "libelle", "action", "arrival_date", "shopify_status",
              "current_template", "current_oversell", "reason", "applied"]
    with open(REPORT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # обобщение
    from collections import Counter
    c = Counter(r["action"] for r in rows)
    print("\n=== ОБОБЩЕНИЕ ===")
    for k, n in c.items():
        print(f"  {k}: {n}")
    print(f"  (пропуснати — други доставчици: {skipped_other_vendor})")
    print(f"\nОтчет записан: {REPORT_FILE}")
    if DRY_RUN:
        print(">>> Това беше ТЕСТ (DRY RUN) — НИЩО не е променено в Shopify.")
        print(">>> Прегледай CSV-то. За реален запис изключи DRY RUN в")
        print(">>> приложението или пусни скрипта с --real-run.")
    else:
        errs = sum(1 for r in rows if str(r["applied"]).startswith("ERROR"))
        print(f">>> РЕАЛЕН режим. Приложени промени: "
              f"{sum(1 for r in rows if r['applied'] == 'applied')}"
              + (f" | грешки: {errs}" if errs else ""))


if __name__ == "__main__":
    main()
