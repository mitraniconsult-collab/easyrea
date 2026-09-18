#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Взима Shopify Admin API токен чрез Client Credentials Grant
(новият начин — Dev Dashboard app с Client ID + Secret).
После проверява токена и изважда Location ID.
"""
import os
import requests

STORE         = os.environ.get("SHOPIFY_STORE", "your-store.myshopify.com")
CLIENT_ID     = os.environ.get("SHOPIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
API           = "2026-04"

if not CLIENT_ID or not CLIENT_SECRET or "your-store" in STORE:
    print("ГРЕШКА: задай първо:")
    print("  set SHOPIFY_STORE=твоя-магазин.myshopify.com")
    print("  set SHOPIFY_CLIENT_ID=...")
    print("  set SHOPIFY_CLIENT_SECRET=...")
    raise SystemExit(1)


def get_token():
    url = f"https://{STORE}/admin/oauth/access_token"
    r = requests.post(url, json={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=30)
    print("Token заявка HTTP статус:", r.status_code)
    if r.status_code != 200:
        print("Отговор:", r.text[:400])
        raise SystemExit(1)
    data = r.json()
    token = data.get("access_token")
    print("Токен получен:", (token[:12] + "...") if token else "НЯМА")
    print("Изтича след (сек):", data.get("expires_in", "n/a"))
    return token


def check(token):
    q = "{ locations(first: 20) { nodes { id name isActive shipsInventory } } }"
    r = requests.post(
        f"https://{STORE}/admin/api/{API}/graphql.json",
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
        json={"query": q}, timeout=30,
    )
    print("\nПроверка на токена — HTTP статус:", r.status_code)
    data = r.json()
    if "errors" in data:
        print("Грешка (вероятно липсващ scope):", data["errors"])
        return
    print("\n=== Локации ===")
    for n in data["data"]["locations"]["nodes"]:
        flag = "  <-- използвай тази" if (n["isActive"] and n["shipsInventory"]) else ""
        print(f'  {n["id"]}   {n["name"]}{flag}')


if __name__ == "__main__":
    t = get_token()
    check(t)
