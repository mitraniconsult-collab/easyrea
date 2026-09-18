#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/scripts.py — регистър на скриптовете.

ЕДНО място, което описва какво може да прави приложението. Ако утре
добавим нов скрипт (напр. sync_prices.py), той се добавя САМО тук и
се появява автоматично в интерфейса.

Полета:
    file      — име на .py файла в папката със скриптовете
    label     — какво пише на бутона
    desc      — кратко обяснение под бутона
    group     — в коя секция да се покаже
    dry_run   — приема ли --dry-run / --real-run
    batch     — приема ли --batch-size / --batch-number
    writes    — променя ли нещо в Shopify (само за предупреждения)
    minutes   — груба оценка за времетраене (за информация на потребителя)
    every_days — на колко дни трябва да се пуска (0 = няма график)
    reports   — шаблони на файловете с отчети, които произвежда
"""

from dataclasses import dataclass


GROUP_REGULAR = "Редовни задачи"
GROUP_ONEOFF = "Еднократни"
GROUP_REPORTS = "Отчети (само четене)"

GROUP_ORDER = [GROUP_REGULAR, GROUP_ONEOFF, GROUP_REPORTS]


@dataclass(frozen=True)
class ScriptDef:
    file: str
    label: str
    desc: str
    group: str
    dry_run: bool = False
    batch: bool = False
    writes: bool = False
    minutes: int = 0
    every_days: int = 0
    reports: tuple = ()

    @property
    def key(self):
        return self.file

    @property
    def scheduled(self):
        return self.every_days > 0


SCRIPTS = [
    ScriptDef(
        file="sync.py",
        label="Синхронизирай наличности",
        desc="Главната седмична задача: In stock / In arrival / Missing. "
             "Има предпазна спирачка при над 25% MISSING.",
        group=GROUP_REGULAR,
        dry_run=True, writes=True, minutes=25,
        every_days=7, reports=("sync_report_*.csv",),
    ),
    ScriptDef(
        file="sync_metafield.py",
        label="Синхронизирай дати за пристигане",
        desc="custom.expected_arrival на variant ниво. 2× седмично.",
        group=GROUP_REGULAR,
        dry_run=True, writes=True, minutes=20,
        every_days=3, reports=("metafield_report_*.csv",),
    ),
    ScriptDef(
        file="import_products.py",
        label="Качи нови продукти (AI)",
        desc="БГ заглавие и описание чрез Claude, ценообразуване, "
             "качване като DRAFT. Ползва полетата за партида.",
        group=GROUP_REGULAR,
        dry_run=True, batch=True, writes=True, minutes=45,
        reports=("import_report_*.csv",),
    ),
    ScriptDef(
        file="sync_weight.py",
        label="Синхронизирай теглото",
        desc="Масова еднократна синхронизация на теглото easyrea → Shopify.",
        group=GROUP_ONEOFF,
        dry_run=True, writes=True, minutes=75,
        reports=("weight_report_*.csv",),
    ),
    ScriptDef(
        file="export_missing_skus.py",
        label="Експортирай липсващи SKU-та",
        desc="Текстов файл с всички easyrea SKU-та, които липсват в Shopify.",
        group=GROUP_REPORTS,
        minutes=15, reports=("missing_skus_*.txt",),
    ),
    ScriptDef(
        file="find_variations.py",
        label="Намери вариации (един модел)",
        desc="Групира SKU-тата по обща числова основа (186674A/B/C). "
             "Excel отчет с 2 листа.",
        group=GROUP_REPORTS,
        minutes=10, reports=("variations_report.xlsx", "variations_report.txt"),
    ),
]

BY_FILE = {s.file: s for s in SCRIPTS}


def by_group():
    """Връща [(група, [скриптове]), …] в подредбата от GROUP_ORDER."""
    out = []
    for g in GROUP_ORDER:
        items = [s for s in SCRIPTS if s.group == g]
        if items:
            out.append((g, items))
    return out
