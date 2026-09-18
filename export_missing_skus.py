#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генерира прост текстов файл с easyrea кодове (SKU),
които ЛИПСВАТ в Shopify — по един на ред.
"""
import os, sys, time, json, datetime, requests

import runtime

_CREDS = runtime.require_env(
    "EASYREA_LOGIN", "EASYREA_PASSWORD",
    "SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
)
EASYREA_LOGIN         = _CREDS["EASYREA_LOGIN"]
EASYREA_PASSWORD      = _CREDS["EASYREA_PASSWORD"]
SHOPIFY_STORE         = _CREDS["SHOPIFY_STORE"]
SHOPIFY_CLIENT_ID     = _CREDS["SHOPIFY_CLIENT_ID"]
SHOPIFY_CLIENT_SECRET = _CREDS["SHOPIFY_CLIENT_SECRET"]
SHOPIFY_API_VER  = "2026-04"
CODE_MAGASIN     = "26284"
SUFFIXE_MAGASIN  = "1"
EASYREA_BASE     = "https://api-prod.easyrea.com/private/api/easyrea"
PAGE_SIZE        = 200

OUTPUT = f"missing_skus_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"


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


def easyrea_all_codes(s, xsrf):
    url = f"{EASYREA_BASE}/magasins/{CODE_MAGASIN}/{SUFFIXE_MAGASIN}/produits"
    codes = set()
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
            if code:
                codes.add(code)
        print(f"[easyrea] стр.{page} → {len(codes)} кода")
        page += 1
        if total and (page - 1) * PAGE_SIZE >= total:
            break
        time.sleep(0.3)
    return codes


def shopify_all_skus():
    r = requests.post(f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
                      json={"grant_type": "client_credentials",
                            "client_id": SHOPIFY_CLIENT_ID,
                            "client_secret": SHOPIFY_CLIENT_SECRET}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"[shopify] Токен OK")
    skus, cursor = set(), None
    q = """query($c:String){productVariants(first:200,after:$c){
      pageInfo{hasNextPage endCursor} nodes{sku}}}"""
    while True:
        r = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VER}/graphql.json",
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            json={"query": q, "variables": {"c": cursor}}, timeout=60)
        r.raise_for_status()
        data = r.json()["data"]["productVariants"]
        for n in data["nodes"]:
            s = (n.get("sku") or "").strip()
            if s:
                skus.add(s)
        if data["pageInfo"]["hasNextPage"]:
            cursor = data["pageInfo"]["endCursor"]
        else:
            break
    print(f"[shopify] Общо SKU: {len(skus)}")
    return skus


def main():
    print("=== Намиране на липсващи SKU-та ===")
    s, xsrf = easyrea_login()
    easyrea_codes = easyrea_all_codes(s, xsrf)
    shopify_skus  = shopify_all_skus()

    missing = sorted(easyrea_codes - shopify_skus)
    print(f"\nEasyRea: {len(easyrea_codes)} | Shopify: {len(shopify_skus)} | Липсват: {len(missing)}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(missing))

    print(f"Записано в: {OUTPUT}")


if __name__ == "__main__":
    main()
