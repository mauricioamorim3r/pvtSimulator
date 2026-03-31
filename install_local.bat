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

echo [1/5] Verificando Python 3.13...
py -3.13 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.13 nao encontrado nesta maquina.
    echo Instale o Python 3.13 e rode novamente este arquivo.
    pause
    exit /b 1
)

echo [2/5] Criando ambiente virtual local...
if exist ".\.venv\Scripts\python.exe" (
    echo .venv ja existe. Reutilizando ambiente local.
) else (
    py -3.13 -m venv .venv
    if errorlevel 1 (
        echo Falha ao criar .venv
        pause
        exit /b 1
    )
)

echo [3/5] Atualizando pip/setuptools/wheel...
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo Falha ao atualizar ferramentas base do pip.
    pause
    exit /b 1
)

echo [4/5] Instalando dependencias do projeto...
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo Falha na instalacao das dependencias.
    echo Dica: confirme se o Java JDK 17 esta instalado e se voce nao esta usando Python 3.14.
    pause
    exit /b 1
)

echo [5/5] Validando NeqSim...
.\.venv\Scripts\python.exe -c "from neqsim.thermo import fluid; print('neqsim ok')"
if errorlevel 1 (
    echo Dependencias instaladas, mas o NeqSim nao iniciou.
    echo Verifique JAVA_HOME e se o comando java -version funciona neste terminal.
    if defined JAVA_HOME (
        echo JAVA_HOME detectado neste instalador: %JAVA_HOME%
    ) else (
        echo JAVA_HOME nao foi detectado automaticamente.
    )
    pause
    exit /b 1
)

echo.
echo Ambiente pronto.
echo Para rodar a aplicacao, use run_local.bat
pause
