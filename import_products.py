#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline за качване на нови продукти от easyrea в Shopify.

Стъпки за всеки продукт:
  1. Взима данни от easyrea (listing + fiche-produit)
  2. Claude API генерира заглавие (БГ) + описание (БГ, SEO)
  3. Изчислява продажна цена по ценовата таблица
  4. Качва в Shopify като DRAFT с 1 снимка, SKU, баркод

Използване:
  От приложението — попълни BATCH_SIZE и BATCH_NUMBER и натисни бутона.
  Ръчно:
      python3 import_products.py --batch-size 500 --batch-number 1 --dry-run
      python3 import_products.py --batch-size 500 --batch-number 1 --real-run

  Партида 1 = първите N липсващи продукта, партида 2 = следващите N и т.н.
  Тайните се четат от environment — в този файл ги няма. Виж runtime.py.
"""

import os, re, sys, time, json, datetime, csv, math, requests

import runtime

# ── Credentials ─────────────────────────────────────────────────────────────
# Всичко идва от environment. В този файл НЯМА тайни.
_CREDS = runtime.require_env(
    "EASYREA_LOGIN", "EASYREA_PASSWORD",
    "SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
    "ANTHROPIC_API_KEY",
)
EASYREA_LOGIN         = _CREDS["EASYREA_LOGIN"]
EASYREA_PASSWORD      = _CREDS["EASYREA_PASSWORD"]
SHOPIFY_STORE         = _CREDS["SHOPIFY_STORE"]
SHOPIFY_CLIENT_ID     = _CREDS["SHOPIFY_CLIENT_ID"]
SHOPIFY_CLIENT_SECRET = _CREDS["SHOPIFY_CLIENT_SECRET"]
ANTHROPIC_API_KEY     = _CREDS["ANTHROPIC_API_KEY"]
SHOPIFY_API_VER       = "2026-04"
CODE_MAGASIN          = "26284"
SUFFIXE_MAGASIN       = "1"
EASYREA_BASE          = "https://api-prod.easyrea.com/private/api/easyrea"

# ── Настройки (от приложението / командния ред) ──────────────────────────────
DRY_RUN      = runtime.dry_run(default=True)      # DRY_RUN / --dry-run / --real-run
BATCH_SIZE   = runtime.batch_size(default=500)    # BATCH_SIZE / --batch-size N
BATCH_NUMBER = runtime.batch_number(default=1)    # BATCH_NUMBER / --batch-number N

# Vendor mapping: easyrea marque -> Shopify vendor
VENDOR_MAP = {
    "ATMOSPHERA": "atmosphera",
    "FIVE":       "5five",
    "HESPERIDE":  "Hesperide",
    "SECRET DE GOURMET": "Secret De Gourmet",
    "FEERIC":     "Feeric",
}

REPORT = f"import_report_batch{BATCH_NUMBER}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ── Ценова таблица ────────────────────────────────────────────────────────────
PRICE_TABLE = [
    (5,    3.20, 5),   (10,  3.15, 5),  (15,  3.10, 5),
    (20,   3.05, 5),   (25,  3.00, 5),  (30,  2.95, 5),
    (35,   2.90, 5),   (40,  2.85, 5),  (45,  2.80, 5),
    (50,   2.75, 5),   (55,  2.70, 15), (70,  2.65, 15),
    (85,   2.60, 15),  (100, 2.55, 15), (115, 2.50, 15),
    (130,  2.45, 15),  (145, 2.40, 15), (160, 2.35, 15),
    (205,  2.30, 45),  (250, 2.25, 45), (295, 2.20, 45),
    (340,  2.15, 45),  (385, 2.10, 45), (430, 2.05, 45),
    (475,  2.00, 45),  (9999, 2.00, 45),
]

def calculate_price(cost_eur):
    """Изчислява продажна цена по ценовата таблица."""
    if not cost_eur or cost_eur <= 0:
        return None
    multiplier = 2.00
    step = 45
    for threshold, mult, stp in PRICE_TABLE:
        if cost_eur <= threshold:
            multiplier = mult
            step = stp
            break
    raw = cost_eur * multiplier
    price = round(raw / step) * step
    if price < step:
        price = step
    return price


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
        raise RuntimeError(f"EasyRea логин неуспешен: {r.status_code} {r.text[:200]}")
    xsrf = s.cookies.get("xsrf-token")
    if not xsrf:
        import base64
        tok = s.cookies.get("token", "")
        if tok:
            p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
            xsrf = json.loads(base64.urlsafe_b64decode(p)).get("xsrfToken")
    print(f"[easyrea] Логин OK")
    return s, xsrf


def easyrea_fetch_all(s, xsrf):
    """Взима всички продукти от listing-а."""
    url = f"{EASYREA_BASE}/magasins/{CODE_MAGASIN}/{SUFFIXE_MAGASIN}/produits"
    out = {}
    page, total = 1, None
    PAGE_SIZE = 200
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
        if r.status_code == 404:
            raise RuntimeError(
                "EasyRea върна 404 — сесията е изтекла. "
                "Затвори и отвори нов cmd прозорец, задай credentials пак и стартирай скрипта."
            )
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
                out[code] = p
        print(f"[easyrea] стр.{page} → {len(out)}")
        page += 1
        if total and (page - 1) * PAGE_SIZE >= total:
            break
        time.sleep(0.3)
    return out


def easyrea_fiche(s, xsrf, sku, retries=5):
    """Взима пълната карта на продукта от /fiche-produit."""
    url = f"{EASYREA_BASE}/magasins/{CODE_MAGASIN}/{SUFFIXE_MAGASIN}/fiche-produit/{sku}"
    for attempt in range(retries):
        try:
            r = s.post(url, json={}, timeout=30, headers={
                "Content-Type": "application/json;charset=UTF-8",
                "x-csrf-token": xsrf, "lang": "en",
                "Referer": f"https://easyrea.com/produits/{sku}",
            })
            if r.status_code == 404:
                return None
            if r.status_code in (502, 503, 504):
                wait = (attempt + 1) * 5
                print(f"    [fiche retry {attempt+1}/{retries}] {r.status_code}. Изчаквам {wait}с...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < retries - 1:
                time.sleep((attempt + 1) * 2)
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


def shopify_get_all_skus(token):
    """Взима всички съществуващи SKU от Shopify."""
    skus = set()
    cursor = None
    q = """query($c:String){productVariants(first:200,after:$c){
      pageInfo{hasNextPage endCursor} nodes{sku}}}"""
    while True:
        d = gql(token, q, {"c": cursor})
        data = d["productVariants"]
        for n in data["nodes"]:
            s = (n.get("sku") or "").strip()
            if s:
                skus.add(s)
        if data["pageInfo"]["hasNextPage"]:
            cursor = data["pageInfo"]["endCursor"]
        else:
            break
    print(f"[shopify] Съществуващи SKU: {len(skus)}")
    return skus


def shopify_create_product(token, title, description_html, vendor,
                            sku, barcode, price, cost, image_urls, weight_g=None):
    """Качва продукт в Shopify като DRAFT — нов API 2026-04."""

    # Стъпка 1: Създай продукта (без варианти)
    q_product = """
    mutation($product: ProductCreateInput!) {
      productCreate(product: $product) {
        product { id title handle }
        userErrors { field message }
      }
    }"""
    result = gql(token, q_product, {
        "product": {
            "title": title,
            "descriptionHtml": description_html,
            "vendor": vendor,
            "status": "DRAFT",
        }
    })
    errors = (result.get("productCreate") or {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"productCreate грешка: {errors}")

    product_id = (result.get("productCreate", {}).get("product") or {}).get("id")
    if not product_id:
        raise RuntimeError("productCreate не върна product ID")

    # Стъпка 2: Обнови дефолтния вариант
    q_get_variant = """
    query($id: ID!) {
      product(id: $id) {
        variants(first: 1) { nodes { id } }
      }
    }"""
    v_data = gql(token, q_get_variant, {"id": product_id})
    default_variant_id = v_data["product"]["variants"]["nodes"][0]["id"]

    q_variant = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id sku price }
        userErrors { field message }
      }
    }"""
    variant_input = {
        "id": default_variant_id,
        "price": f"{float(price):.2f}",
        "barcode": str(barcode) if barcode else "",
        "inventoryPolicy": "CONTINUE",
        "inventoryItem": {
            "sku": str(sku),
            "tracked": True,
            "cost": f"{float(cost):.2f}" if cost else None,
        },
    }
    if not cost:
        del variant_input["inventoryItem"]["cost"]
    # Тегло от fiche-produit
    if weight_g:
        variant_input["inventoryItem"]["measurement"] = {
            "weight": {"value": weight_g, "unit": "GRAMS"}
        }

    v_result = gql(token, q_variant, {
        "productId": product_id,
        "variants": [variant_input]
    })
    v_errors = (v_result.get("productVariantsBulkUpdate") or {}).get("userErrors", [])
    if v_errors:
        print(f"    [вариант] Грешка: {v_errors}")

    # Стъпка 3: Добави всички снимки (с малко забавяне)
    if product_id and image_urls:
        time.sleep(1)  # изчакай Shopify да финализира продукта
        q_media = """
        mutation($productId: ID!, $media: [CreateMediaInput!]!) {
          productCreateMedia(productId: $productId, media: $media) {
            media { ... on MediaImage { id status } }
            mediaUserErrors { field message }
          }
        }"""
        media_input = [
            {"originalSource": url, "mediaContentType": "IMAGE", "alt": title}
            for url in image_urls if url
        ]
        if media_input:
            try:
                r = gql(token, q_media, {"productId": product_id, "media": media_input})
                m_errors = r.get("productCreateMedia", {}).get("mediaUserErrors", [])
                if m_errors:
                    print(f"    [снимки] Грешка: {m_errors}")
                else:
                    print(f"    [снимки] {len(media_input)} качени")
            except Exception as e:
                print(f"    [снимки] Грешка: {e}")

    return result


# ── Claude API ────────────────────────────────────────────────────────────────
def claude_generate(listing, fiche):
    """Генерира заглавие и описание на български чрез Claude API."""
    if not ANTHROPIC_API_KEY:
        return None, None

    # Събери информацията
    tech = (fiche or {}).get("informationsTechniques") or {}
    descr = (fiche or {}).get("descriptifProduit") or {}
    descriptif_web = descr.get("descriptifWeb", "")
    libelles = " | ".join([v for k, v in descr.items()
                           if k.startswith("libelle") and v])

    prompt = f"""Ти си копирайтър за български онлайн магазин за дома и декорация.

Информация за продукта:
- Английско наименование: {listing.get("libelle", "")}
- Марка: {listing.get("marque", "")}
- Колекция: {listing.get("collection", "")}
- Материал: {tech.get("matiere", "")}
- Цвят: {tech.get("couleur", "")}
- Размери: {tech.get("dimensionProduit", "")}
- Тегло: {tech.get("poidsProduit", "")}
- Описание (FR): {descriptif_web}
- Характеристики: {libelles}

ЗАДАЧА 1 — ЗАГЛАВИЕ:
Стандарт: "Тип продукт Бранд Модел, Основна характеристика"
Примери: "Въртящ се фотьойл atmosphera Stelan, Шенил, Амбър"
         "Кош за пране 5five, Метал, 30L, Син"
         "Детско бюро atmosphera, MDF, 140 cm"
Марката се изписва точно така: atmosphera, 5five, Hesperide, Secret De Gourmet, Feeric
Заглавието трябва да е на български, кратко и ясно.

ЗАДАЧА 2 — ОПИСАНИЕ:
Създай SEO оптимизирано описание на български с:
1. Кратък маркетингов увод (2-3 изречения) — защо клиентът да го купи
2. Основни предимства (3-5 bullet точки с •)
3. Технически характеристики в отделен параграф

Форматирай като HTML с <p>, <ul><li> тагове.

Отговори САМО в JSON формат (без markdown):
{{"title": "...", "description": "..."}}"""

    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            r.raise_for_status()
            content = r.json()["content"][0]["text"].strip()
            # Изчисти markdown ако има
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            data = json.loads(content)
            return data.get("title"), data.get("description")
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"  [claude] Грешка: {e}")
                return None, None
    return None, None


# ── ГЛАВНА ФУНКЦИЯ ────────────────────────────────────────────────────────────
def main():
    runtime.print_mode_banner(
        "EasyRea → Shopify · качване на нови продукти", DRY_RUN,
        extra=f"Партида {BATCH_NUMBER} · по {BATCH_SIZE} продукта")

    # 1. Логин
    s, xsrf = easyrea_login()
    token = shopify_token()

    # 2. Вземи всички продукти от easyrea
    all_easyrea = easyrea_fetch_all(s, xsrf)

    # 3. Вземи съществуващите SKU от Shopify
    existing_skus = shopify_get_all_skus(token)

    # 4. Намери липсващите
    missing = [(code, p) for code, p in all_easyrea.items()
               if code not in existing_skus]
    print(f"\n[резултат] Липсват в Shopify: {len(missing)}")

    # 5. Вземи партидата
    start = (BATCH_NUMBER - 1) * BATCH_SIZE
    end = start + BATCH_SIZE
    batch = missing[start:end]
    print(f"[партида] {BATCH_NUMBER}: продукти {start+1}-{min(end, len(missing))} ({len(batch)} бр.)")

    if not batch:
        last = (len(missing) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n[край] Партида {BATCH_NUMBER} е празна — при размер {BATCH_SIZE} "
              f"има само {last} партиди. Нищо не е направено.")
        return

    # 6. Обработи всеки продукт
    stats = {"CREATED": 0, "SKIP_NO_PRICE": 0, "SKIP_NO_IMAGE": 0,
             "SKIP_NO_TITLE": 0, "ERROR": 0}
    rows = []

    for i, (sku, listing) in enumerate(batch, 1):
        print(f"PROGRESS {i}/{len(batch)}", flush=True)
        print(f"  [{i}/{len(batch)}] {sku} — {listing.get('libelle', '')[:40]}")

        # Доставна цена (в центове → евро)
        cost_cents = listing.get("prixAchat") or 0
        cost_eur = cost_cents / 100 if cost_cents else 0

        if not cost_eur:
            stats["SKIP_NO_PRICE"] += 1
            rows.append({"sku": sku, "action": "SKIP_NO_PRICE",
                         "note": "Няма доставна цена"})
            continue

        # Fiche-produit за описание и снимки
        fiche = easyrea_fiche(s, xsrf, sku)
        time.sleep(0.4)

        # Снимки — вземи всички от fiche-produit
        image_urls = []
        if fiche:
            photos = fiche.get("listePhotos") or []
            for photo in photos:
                url = photo.get("url") or photo.get("urlPhoto") or photo.get("urlImage")
                if url and url not in image_urls:
                    image_urls.append(url)
        # Fallback към listing снимките ако няма от fiche
        if not image_urls:
            for key in ["photoPrincipale", "photoAmbiance"]:
                url = listing.get(key)
                if url and url not in image_urls:
                    image_urls.append(url)
        if not image_urls:
            stats["SKIP_NO_IMAGE"] += 1
            rows.append({"sku": sku, "action": "SKIP_NO_IMAGE", "note": "Няма снимка"})
            continue

        # Тегло от fiche-produit
        weight_g = None
        if fiche:
            import re
            tech = (fiche.get("informationsTechniques") or {})
            poids = tech.get("poidsProduit", "")
            if poids:
                match = re.search(r'([\d.,]+)\s*(kg|g)', str(poids).lower())
                if match:
                    val = float(match.group(1).replace(',', '.'))
                    weight_g = int(val * 1000) if match.group(2) == 'kg' else int(val)

        # Claude генерира заглавие + описание
        title, description = claude_generate(listing, fiche)
        time.sleep(0.5)  # Rate limit за Claude

        if not title:
            # Fallback — използвай английското наименование
            title = listing.get("libelle", sku)
            description = f"<p>{listing.get('libelle', '')}</p>"
            print(f"    [fallback] Използвам EN заглавие")

        # Продажна цена
        sell_price = calculate_price(cost_eur)

        # Vendor
        marque = (listing.get("marque") or "").upper()
        vendor = VENDOR_MAP.get(marque, listing.get("marque", ""))

        # Баркод — задължително string
        barcode = str(listing.get("gencode", "") or "").strip()

        action = "CREATE"
        note = f"{cost_eur:.2f}€ → {sell_price}€ | {title[:50]}"

        if not DRY_RUN:
            try:
                result = shopify_create_product(
                    token, title, description, vendor,
                    sku, barcode, sell_price, cost_eur, image_urls, weight_g
                )
                errors = result.get("productCreate", {}).get("userErrors", [])
                if errors:
                    action = "ERROR"
                    note = str(errors)[:200]
                    stats["ERROR"] += 1
                else:
                    stats["CREATED"] += 1
                time.sleep(0.5)
            except Exception as e:
                action = "ERROR"
                note = str(e)[:300]
                stats["ERROR"] += 1
        else:
            stats["CREATED"] += 1

        rows.append({
            "sku": sku,
            "barcode": barcode,
            "vendor": vendor,
            "title": title,
            "description": (description or "")[:2000],
            "cost_eur": cost_eur,
            "sell_price": sell_price,
            "image_url": image_urls[0] if image_urls else "",
            "action": action,
            "note": note,
        })

        if i % 50 == 0:
            print(f"  [прогрес] {i}/{len(batch)} | "
                  f"CREATE:{stats['CREATED']} ERROR:{stats['ERROR']}")

    # Отчет
    if rows:
        fieldnames = ["sku", "barcode", "vendor", "title", "description",
                      "cost_eur", "sell_price", "image_url", "action", "note"]
        with open(REPORT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    print(f"\n=== ОБОБЩЕНИЕ (Партида {BATCH_NUMBER}) ===")
    for k, n in stats.items():
        if n:
            print(f"  {k}: {n}")
    print(f"\nОтчет: {REPORT}")
    if DRY_RUN:
        print(">>> ТЕСТ (DRY RUN) — нищо не е качено в Shopify.")
        print(">>> Прегледай отчета. За реално качване изключи DRY RUN в")
        print(">>> приложението или пусни с --real-run.")
    else:
        print(f">>> РЕАЛЕН режим — качени са {stats['CREATED']} нови продукта "
              f"като DRAFT.")


if __name__ == "__main__":
    main()
