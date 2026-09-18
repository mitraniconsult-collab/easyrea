#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_variations.py — намира SKU-та, които са един модел с няколко вариации,
и записва Excel отчет с ДВА листа:
    • „За обединяване"  — вариациите седят в НЯКОЛКО ЖИВИ (Active/Draft) продукта
                          → трябва да се слеят в 1 продукт с няколко варианта
    • „Вече обединени"  — вариациите вече са в ЕДИН жив продукт
                          (ако има стари ARCHIVED дубликати, се отчитат отделно)

ВАЖНО за класификацията:
  В Shopify един и същи SKU може да стои в няколко продукта — типично 1 активен
  (обединеният) + няколко архивни (старите единични продукти по цвят). Затова за
  решението „обединен ли е" се броят САМО ЖИВИТЕ продукти (status != ARCHIVED).
  Архивните се показват само като „Архивни дубликати" (кандидати за изтриване).

ЛОГИКА на групирането:
  SKU = числова ОСНОВА + (по избор) БУКВЕН СУФИКС.  '146202A' → основа 146202.
  Самостоятелните SKU-та (без суфикс-братя) НЕ се броят за вариации.

Само ЧЕТЕ. Нищо не променя в Shopify. Изход: variations_report.xlsx
АВТЕНТИКАЦИЯ: същата като sync.py (client credentials grant + GraphQL).

РЕЖИМИ:
  python find_variations.py                       → тегли всички продукти от Shopify
  python find_variations.py --from-file skus.txt  → чете от файл (за тест)
        Ред: SKU[,product_id[,status]]   (разделител запетая/таб/;)
        Липсва product_id → всеки SKU е свой продукт.  Липсва status → ACTIVE.

Изисквания:  pip install requests openpyxl
"""

import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").strip()
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
SHOPIFY_API_VER = "2026-04"

XLSX_FILE = "variations_report.xlsx"
TXT_FILE = "variations_report.txt"


def log(msg=""):
    print(msg, flush=True)


# ════════════════════════════════════════════════════════════════════════
#  Основа / суфикс
# ════════════════════════════════════════════════════════════════════════
def base_of(sku):
    m = re.match(r"(\d+)", sku)
    return m.group(1) if m else sku


def suffix_of(sku, base):
    return sku[len(base):] if sku.startswith(base) else ""


# ════════════════════════════════════════════════════════════════════════
#  Shopify (същата логика като в sync.py)
# ════════════════════════════════════════════════════════════════════════
class Shopify:
    def __init__(self):
        import requests
        self._rq = requests
        if not SHOPIFY_STORE or "your-store" in SHOPIFY_STORE:
            raise RuntimeError("Задай SHOPIFY_STORE.")
        self.base = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VER}"
        token = self._get_token()
        self.headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    def _get_token(self):
        if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
            raise RuntimeError("Задай SHOPIFY_CLIENT_ID и SHOPIFY_CLIENT_SECRET.")
        r = self._rq.post(
            f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
            json={"grant_type": "client_credentials",
                  "client_id": SHOPIFY_CLIENT_ID,
                  "client_secret": SHOPIFY_CLIENT_SECRET},
            timeout=30)
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            raise RuntimeError(f"Токенът не е получен: {r.text[:200]}")
        log(f"[shopify] Токен получен: {token[:12]}...")
        return token

    def gql(self, query, variables=None):
        r = self._rq.post(f"{self.base}/graphql.json", headers=self.headers,
                          json={"query": query, "variables": variables or {}}, timeout=60)
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"Shopify GraphQL error: {data['errors']}")
        cost = data.get("extensions", {}).get("cost", {})
        if cost.get("throttleStatus", {}).get("currentlyAvailable", 1000) < 200:
            time.sleep(2)
        return data["data"]

    def fetch_all_variants(self):
        out = []
        cursor = None
        q = """
        query($cursor: String) {
          productVariants(first: 200, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes { sku product { id title status vendor } }
          }
        }"""
        while True:
            d = self.gql(q, {"cursor": cursor})
            conn = d["productVariants"]
            for n in conn["nodes"]:
                sku = (n.get("sku") or "").strip().upper()
                if not sku:
                    continue
                p = n["product"]
                out.append({
                    "sku": sku,
                    "product_id": p["id"],
                    "title": p.get("title", ""),
                    "status": (p.get("status") or "").strip().upper(),
                    "vendor": (p.get("vendor") or "").strip(),
                })
            if conn["pageInfo"]["hasNextPage"]:
                cursor = conn["pageInfo"]["endCursor"]
                log(f"[shopify] заредени варианти: {len(out)}")
            else:
                break
        log(f"[shopify] Общо варианти със SKU: {len(out)}")
        return out


def read_file_skus(path):
    """Ред: SKU[,product_id[,status]]. Липсва pid → сам себе си. Липсва статус → ACTIVE."""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in re.split(r"[,\t;]", line)]
            sku = parts[0].upper()
            if not sku:
                continue
            pid = parts[1] if len(parts) > 1 and parts[1] else sku
            status = (parts[2].upper() if len(parts) > 2 and parts[2] else "ACTIVE")
            out.append({"sku": sku, "product_id": pid, "title": "", "status": status, "vendor": ""})
    return out


# ════════════════════════════════════════════════════════════════════════
#  Анализ  (живите продукти решават; архивните се броят отделно)
# ════════════════════════════════════════════════════════════════════════
def _family_stats(vs):
    live = [v for v in vs if v["status"] != "ARCHIVED"]
    live_pids = {v["product_id"] for v in live}
    archived_pids = {v["product_id"] for v in vs if v["status"] == "ARCHIVED"}
    n_skus = len({v["sku"] for v in vs})
    rows = live if live else vs            # показваме живите редове (или всички, ако няма живи)
    return rows, len(live_pids), len(archived_pids), n_skus


def analyze(variants):
    groups = defaultdict(list)
    for v in variants:
        groups[base_of(v["sku"])].append(v)
    families = {b: vs for b, vs in groups.items() if len(vs) >= 2}

    to_merge, merged = [], []
    for b, vs in families.items():
        rows, n_live, n_arch, n_skus = _family_stats(vs)
        entry = (b, rows, n_live, n_arch, n_skus)
        if n_live == 1:
            merged.append(entry)        # обединен в 1 жив продукт
        else:
            to_merge.append(entry)       # 0 или ≥2 живи продукта → за обединяване

    to_merge.sort(key=lambda e: (-e[2], -e[4], e[0]))   # по живи продукти, после размер
    merged.sort(key=lambda e: (-e[3], -e[4], e[0]))     # по архивни дубликати, после размер
    return families, to_merge, merged


# ════════════════════════════════════════════════════════════════════════
#  Excel отчет
# ════════════════════════════════════════════════════════════════════════
HEADERS = ["Основа", "Брой вариации", "Живи продукти", "Архивни дубликати",
           "SKU", "Суфикс", "Заглавие (Shopify)", "Статус", "Vendor", "Shopify Product ID"]
COL_WIDTHS = [14, 13, 14, 16, 18, 8, 40, 10, 16, 30]
TEXT_COLS = {1, 5, 10}       # Основа, SKU, Product ID — текст (пазим водещи нули)
CENTER_COLS = {2, 3, 4, 6}


def _build_sheet(ws, entries):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    head_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2F6FEB")
    data_font = Font(name="Arial", size=10)
    band_fill = PatternFill("solid", fgColor="EEF2F8")
    border = Border(bottom=Side(style="thin", color="D7DCE3"))
    center = Alignment(horizontal="center")

    ws.append(HEADERS)
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    r = 2
    for gi, (base, rows, n_live, n_arch, n_skus) in enumerate(entries, start=1):
        shade = band_fill if gi % 2 == 0 else None
        for v in sorted(rows, key=lambda x: x["sku"]):
            suf = suffix_of(v["sku"], base) or "—"
            data = [base, n_skus, n_live, n_arch, v["sku"], suf,
                    v["title"], v["status"], v["vendor"], v["product_id"]]
            ws.append(data)
            for c in range(1, len(HEADERS) + 1):
                cell = ws.cell(row=r, column=c)
                cell.font = data_font
                if shade:
                    cell.fill = shade
                if c in CENTER_COLS:
                    cell.alignment = center
                if c in TEXT_COLS:
                    cell.number_format = "@"
            r += 1

    for i, w in enumerate(COL_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"
    last = ws.cell(row=1, column=len(HEADERS)).column_letter
    ws.auto_filter.ref = f"A1:{last}{max(r - 1, 1)}"


def write_xlsx(to_merge, merged):
    from openpyxl import Workbook
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "За обединяване"
    _build_sheet(ws1, to_merge)
    ws2 = wb.create_sheet("Вече обединени")
    _build_sheet(ws2, merged)
    wb.save(XLSX_FILE)
    return os.path.abspath(XLSX_FILE)


def write_txt_fallback(to_merge, merged):
    def block(title, entries):
        lines = [title, "=" * 70]
        for base, rows, n_live, n_arch, n_skus in entries:
            lines.append(f"\nОснова {base}  ({n_skus} вариации | живи продукти: {n_live} | архивни: {n_arch})")
            for v in sorted(rows, key=lambda x: x["sku"]):
                lines.append(f"    {v['sku']:>14}  [{v['status']}]  {v['title']}")
        return "\n".join(lines)

    text = (f"ОТЧЕТ: модели с няколко вариации   {datetime.now():%Y-%m-%d %H:%M}\n\n"
            + block("ЗА ОБЕДИНЯВАНЕ (в няколко живи продукта)", to_merge)
            + "\n\n\n" + block("ВЕЧЕ ОБЕДИНЕНИ (в един жив продукт)", merged) + "\n")
    with open(TXT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.abspath(TXT_FILE)


# ════════════════════════════════════════════════════════════════════════
#  Главна функция
# ════════════════════════════════════════════════════════════════════════
def main():
    args = sys.argv[1:]
    if "--from-file" in args:
        i = args.index("--from-file")
        path = args[i + 1] if i + 1 < len(args) else ""
        if not path or not os.path.isfile(path):
            log("[ГРЕШКА] Подай валиден файл: --from-file път/към/skus.txt")
            sys.exit(2)
        log(f"Режим: четене на SKU-та от файл — {path}")
        variants = read_file_skus(path)
    else:
        log("Режим: теглене на всички продукти от Shopify…")
        try:
            variants = Shopify().fetch_all_variants()
        except Exception as e:  # noqa: BLE001
            log(f"[ГРЕШКА] {type(e).__name__}: {e}")
            sys.exit(2)

    log(f"✓ Заредени {len(variants)} SKU-та.\n")

    families, to_merge, merged = analyze(variants)
    log(f"Намерени {len(families)} фамилии с по няколко вариации:")
    log(f"   • за обединяване (в няколко живи продукта): {len(to_merge)}")
    log(f"   • вече обединени (в един жив продукт):       {len(merged)}")
    arch_left = sum(1 for e in merged if e[3] > 0)
    if arch_left:
        log(f"   • от обединените, {arch_left} имат архивни дубликати за изтриване")

    try:
        import openpyxl  # noqa: F401
        path = write_xlsx(to_merge, merged)
        log(f"\nExcel отчет (2 листа): {path}")
    except ImportError:
        path = write_txt_fallback(to_merge, merged)
        log("\n[ВНИМАНИЕ] openpyxl липсва — записах TXT вместо Excel.")
        log("           За Excel формат изпълни:  pip install openpyxl")
        log(f"           TXT отчет: {path}")


if __name__ == "__main__":
    main()
