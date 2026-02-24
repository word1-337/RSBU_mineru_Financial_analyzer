@echo off
chcp 65001 >nul
setlocal

echo === Установка зависимостей агента финансовой устойчивости ===

REM Проверка Python
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ОШИБКА] Python не найден в PATH.
    echo Установи Python 3.10 или 3.11 и запусти скрипт снова.
    pause
    exit /b 1
)

echo.
echo [Шаг 1] Обновляю pip ...
python -m pip install --upgrade pip

echo.
echo [Шаг 2] Устанавливаю зависимости из requirements.txt ...
pip install -r requirements.txt

echo.
echo [OK] Зависимости установлены.
echo.
echo Для ИИ-вывода через Ollama нужно отдельно:
echo   1) Установить Ollama: https://ollama.com/download
echo   2) Скачать модель: ollama pull qwen2.5:32b
echo.
echo Готово. Для запуска используй run_agent.bat
echo.
pause
endlocal
