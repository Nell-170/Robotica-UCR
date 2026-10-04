@echo off
REM ============================================================
REM NAO-Med - Script de ejecucion (estilo Makefile)
REM ============================================================
REM Uso:
REM   run.bat start     -> Inicia el monitor completo (detecta NAO
REM                         real o abre Webots automaticamente)
REM   run.bat test       -> Prueba rapida: dispara una notificacion
REM                         de inmediato, sin esperar el cronograma
REM   run.bat schedule   -> Solo muestra el cronograma cargado
REM   run.bat setup      -> Instala OpenCV para Webots (solo simulador)
REM ============================================================
REM Nota sobre Python 2.7: el SDK de NAOqi solo funciona con Python
REM 2.7, no con Python 3. Este script busca automaticamente una
REM instalacion de Python 2.7 en varias rutas comunes (ver
REM :buscar_python mas abajo) para que cada persona del equipo
REM pueda instalarlo donde le resulte mas comodo, sin editar este
REM archivo. Si tu instalacion esta en otra ruta, define la
REM variable de entorno NAOMED_PYTHON27 antes de correr run.bat:
REM   set NAOMED_PYTHON27=D:\herramientas\Python27\python.exe
REM ============================================================

setlocal enabledelayedexpansion

if "%1"=="setup" goto :setup

set SCRIPT_DIR=%~dp0src
set PYTHON27=

call :buscar_python

if "%PYTHON27%"=="" (
    echo [ERROR] No se encontro una instalacion de Python 2.7 en este equipo.
    echo.
    echo Este proyecto requiere Python 2.7 ^(el SDK de NAOqi no funciona con Python 3^).
    echo Instalalo desde: https://www.python.org/downloads/release/python-2718/
    echo ^(descarga el instalador "Windows x86-64 MSI installer"^)
    echo.
    echo Se busco en las siguientes ubicaciones sin exito:
    echo   - "python" en el PATH del sistema
    echo   - C:\Python27-NAOMed\python.exe
    echo   - C:\Python27\python.exe
    echo   - %%LOCALAPPDATA%%\Programs\Python\Python27\python.exe
    echo.
    echo Si lo instalaste en otra ruta, define la variable de entorno
    echo NAOMED_PYTHON27 apuntando al python.exe, por ejemplo:
    echo   set NAOMED_PYTHON27=D:\herramientas\Python27\python.exe
    exit /b 1
)

cd /d "%SCRIPT_DIR%"

if "%1"=="start" goto :start
if "%1"=="test" goto :test
if "%1"=="schedule" goto :schedule
goto :help

:start
echo [NAO-Med] Iniciando monitor completo...
"%PYTHON27%" main.py
goto :eof

:test
echo [NAO-Med] Ejecutando prueba rapida (notificacion inmediata)...
"%PYTHON27%" -c "from robot_connector import main as conectar; from nao_controller import notificar_medicamento; config = conectar(); notificar_medicamento(config, 'Paracetamol')"
goto :eof

:schedule
echo [NAO-Med] Cronograma actual:
"%PYTHON27%" schedule.py
goto :eof

:setup
echo [NAO-Med] Instalando OpenCV para el simulador Webots en webots\libs ...
python -m pip install --no-deps --target "%~dp0webots\libs" "opencv-python==4.11.0.86"
echo [NAO-Med] Requiere numpy en el Python 3 que usa Webots: python -m pip install numpy
goto :eof

:help
echo Uso: run.bat [start^|test^|schedule^|setup]
echo.
echo   start      Inicia el monitor completo de medicamentos
echo   test       Dispara una notificacion de prueba de inmediato
echo   schedule   Muestra el cronograma cargado desde el CSV
echo   setup      Instala OpenCV para el simulador Webots ^(solo simulador^)
exit /b 1

REM ------------------------------------------------------------
REM :buscar_python
REM Busca un Python 2.7 valido, en este orden:
REM   1. Variable de entorno NAOMED_PYTHON27 (override manual)
REM   2. Rutas de instalacion comunes
REM Deja el resultado en la variable PYTHON27 (vacia si no se hallo).
REM ------------------------------------------------------------
:buscar_python
if not "%NAOMED_PYTHON27%"=="" if exist "%NAOMED_PYTHON27%" (
    set PYTHON27=%NAOMED_PYTHON27%
    goto :eof
)

for %%R in (
    "C:\Python27-NAOMed\python.exe"
    "C:\Python27\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python27\python.exe"
) do (
    if exist %%~R (
        set PYTHON27=%%~R
        goto :eof
    )
)
goto :eof
