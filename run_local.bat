@echo off
setlocal

cd /d "%~dp0"

if not defined JAVA_HOME (
    for /d %%D in ("%ProgramFiles%\Eclipse Adoptium\jdk-*") do (
        set "JAVA_HOME=%%~fD"
    )
)

if defined JAVA_HOME (
    set "PATH=%JAVA_HOME%\bin;%PATH%"
)

if not exist ".\.venv\Scripts\python.exe" (
    echo Ambiente local nao encontrado.
    echo Rode primeiro install_local.bat
    pause
    exit /b 1
)

echo Abrindo SIMULPVT Back-Flash local...
if defined JAVA_HOME (
    echo JAVA_HOME em uso: %JAVA_HOME%
)
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
