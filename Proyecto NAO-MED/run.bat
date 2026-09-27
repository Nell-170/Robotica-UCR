@echo off
REM Script para ejecutar NAO-Med con Python 2.7
REM Uso: run.bat main.py
REM       run.bat medication_scheduler.py
REM       etc.

setlocal enabledelayedexpansion

set PYTHON27=C:\Python27-NAOMed\python.exe
set SCRIPT_DIR=%~dp0src

if not exist "%PYTHON27%" (
    echo Error: Python 2.7 no encontrado en %PYTHON27%
    echo Instala Python 2.7 primero.
    exit /b 1
)

if "%1"=="" (
    echo Uso: run.bat SCRIPT.py [ARGUMENTOS]
    echo Ejemplo: run.bat main.py
    exit /b 1
)

cd /d "%SCRIPT_DIR%"
"%PYTHON27%" %*
