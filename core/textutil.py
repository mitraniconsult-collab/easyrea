#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/textutil.py — дребни помощници за текст на български.

Български език има единствено и множествено число, затова „1 грешки"
изглежда небрежно. plural() решава кой вариант да се ползва.
"""


def plural(n, one, many):
    """plural(1, 'грешка', 'грешки') → '1 грешка'"""
    return f"{n} {one if abs(n) == 1 else many}"


def errors(n):
    return plural(n, "грешка", "грешки")


def warnings(n):
    return plural(n, "предупреждение", "предупреждения")


def tasks(n):
    return plural(n, "задача", "задачи")


def products(n):
    return plural(n, "продукт", "продукта")
