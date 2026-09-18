#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyRea ↔ Shopify Sync — стартиране на приложението.
=====================================================

Кодът е разделен на пакети:

    app.py            ← ти си тук: само стартира прозореца
    runtime.py        общ модул за СКРИПТОВЕТЕ (режим + креденшъли)
    core/
        scripts.py    регистър: кои задачи съществуват
        config.py     четене/запис на config.json
        runner.py     опашка от задачи, прогрес, спиране
    ui/
        theme.py      цветове, шрифтове, стилове
        widgets.py    цветен лог, лента за прогрес
        main_window.py обвивка: навигация + помпа за събития
        pages/        Действия · Изпълнение · Настройки

Стартиране:  python app.py   (или двоен клик на run_app.bat)
Изисква само стандартната библиотека (tkinter).
"""

import os
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("Липсва tkinter. Инсталирай Python с включен tkinter.")

    from ui.main_window import MainWindow
    MainWindow().mainloop()


if __name__ == "__main__":
    main()
