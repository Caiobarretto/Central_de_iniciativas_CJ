@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto erro
.venv\Scripts\python.exe -m pip install "playwright>=1.50,<2"
if errorlevel 1 goto erro
echo Pronto. Google Chrome precisa estar instalado. Execute CONFIGURAR_WINDOWS.bat.
pause
exit /b
:erro
echo Falha. Instale Python 3.12 ou superior pelo python.org e tente novamente.
pause
