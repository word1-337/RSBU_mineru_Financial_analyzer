@echo off
chcp 65001 >nul
setlocal

REM Переходим в папку, где лежит этот bat-файл
cd /d "%~dp0"

echo === Запуск агента финансовой устойчивости ===

python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ОШИБКА] Python не найден в PATH.
    echo Установи Python 3.10 или 3.11 и добавь в PATH.
    pause
    exit /b 1
)

echo Открываю веб-интерфейс на http://localhost:8501 ...
python -m streamlit run agent.py

pause
endlocal
