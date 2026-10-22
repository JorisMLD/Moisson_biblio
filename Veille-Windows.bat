@echo off
rem Veille scientifique : lanceur Windows. Double-cliquer sur ce fichier.
rem Au premier lancement : cree un environnement Python isole (.venv) et y
rem installe les dependances. Ensuite : ouvre le menu, ou execute la commande
rem passee en argument (ex. : Veille-Windows.bat routine).
setlocal
cd /d "%~dp0"
title Veille scientifique

if exist ".venv\Scripts\python.exe" goto :deps

echo Premiere utilisation : installation de l'outil (une a deux minutes)...
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :venv
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY goto :nopython

:venv
%PY% -m venv .venv
if errorlevel 1 goto :fail

:deps
fc /b requirements.txt .venv\requirements.installe >nul 2>nul
if not errorlevel 1 goto :run
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto :fail
copy /y requirements.txt .venv\requirements.installe >nul
echo Installation terminee.

:run
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m veille menu
) else (
  ".venv\Scripts\python.exe" -m veille %*
)
goto :end

:nopython
echo.
echo Python 3.9 ou plus recent est introuvable.
echo Installez-le depuis https://www.python.org/downloads/ en cochant la case
echo "Add python.exe to PATH" sur le premier ecran, puis relancez ce fichier.
start "" "https://www.python.org/downloads/"
goto :end

:fail
echo.
echo L'installation a echoue (connexion internet ?).
echo Voir MODE_EMPLOI.md, section Depannage.

:end
if "%~1"=="" pause
endlocal
