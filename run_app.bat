@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Стартиране на EasyRea - Shopify приложението...
python app.py
echo.
echo Приложението е затворено. Натисни клавиш за изход.
pause >nul
