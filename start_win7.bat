@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Keep this file ASCII so cmd.exe on Windows 7 can read it reliably.
rem
rem The Python runtime does NOT have to live inside this project folder.
rem Lookup order:
rem   1. win7-python.txt  (one line, full path to python.exe, no quotes)
rem   2. .\CF37v2\python.exe        (inside the project)
rem   3. ..\CF37v2\python.exe       (beside the project)
rem   4. .\venv\Scripts\python.exe or .\.venv\Scripts\python.exe
rem   5. common Anaconda/Miniconda envs\CF37v2 locations
rem
rem Usage: start_win7.bat            normal start
rem        start_win7.bat --check    environment check only
rem        start_win7.bat --no-browser

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo.
echo ============================================
echo   OCR Project - Win7 Launcher
echo ============================================
echo.

if not exist "%ROOT%\frontend\dist\index.html" (
    echo [ERROR] frontend\dist\index.html was not found.
    echo         Copy the complete project, including frontend\dist.
    if "%~1"=="" pause
    exit /b 1
)

rem ---------- 1. Explicit path from win7-python.txt ----------
set "PY_CMD="
if exist "%ROOT%\win7-python.txt" (
    set /p PY_CMD=<"%ROOT%\win7-python.txt"
)
if defined PY_CMD set "PY_CMD=%PY_CMD:"=%"
if defined PY_CMD if not exist "%PY_CMD%" (
    echo [WARN] win7-python.txt points to a missing file:
    echo        %PY_CMD%
    echo        Fix the path, or save the file as ANSI/UTF-8 without BOM.
    set "PY_CMD="
)

rem ---------- 2. Environment folder inside the project ----------
if not defined PY_CMD if exist "%ROOT%\CF37v2\python.exe" set "PY_CMD=%ROOT%\CF37v2\python.exe"

rem ---------- 3. Environment folder beside the project ----------
if not defined PY_CMD if exist "%ROOT%\..\CF37v2\python.exe" set "PY_CMD=%ROOT%\..\CF37v2\python.exe"

rem ---------- 4. Regular virtual environments ----------
if not defined PY_CMD if exist "%ROOT%\venv\Scripts\python.exe" set "PY_CMD=%ROOT%\venv\Scripts\python.exe"
if not defined PY_CMD if exist "%ROOT%\.venv\Scripts\python.exe" set "PY_CMD=%ROOT%\.venv\Scripts\python.exe"

rem ---------- 5. Common Conda locations ----------
if not defined PY_CMD if exist "%USERPROFILE%\anaconda3\envs\CF37v2\python.exe" set "PY_CMD=%USERPROFILE%\anaconda3\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "%USERPROFILE%\miniconda3\envs\CF37v2\python.exe" set "PY_CMD=%USERPROFILE%\miniconda3\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "C:\ProgramData\Anaconda3\envs\CF37v2\python.exe" set "PY_CMD=C:\ProgramData\Anaconda3\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "C:\ProgramData\Miniconda3\envs\CF37v2\python.exe" set "PY_CMD=C:\ProgramData\Miniconda3\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "D:\Anaconda3\envs\CF37v2\python.exe" set "PY_CMD=D:\Anaconda3\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "D:\ProgramData\Anaconda3\envs\CF37v2\python.exe" set "PY_CMD=D:\ProgramData\Anaconda3\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "E:\Anaconda\envs\CF37v2\python.exe" set "PY_CMD=E:\Anaconda\envs\CF37v2\python.exe"
if not defined PY_CMD if exist "F:\anaconda2024.06\envs\CF37v2\python.exe" set "PY_CMD=F:\anaconda2024.06\envs\CF37v2\python.exe"

if not defined PY_CMD (
    echo [ERROR] No Python runtime was found.
    echo.
    echo         Option A: create win7-python.txt in this folder with ONE line:
    echo                   E:\Anaconda\envs\CF37v2\python.exe
    echo                   ^(use the real path on this computer, no quotes^)
    echo         Option B: copy the complete CF37v2 folder into this project.
    if "%~1"=="" pause
    exit /b 1
)

rem Let a directly invoked conda python.exe find its DLLs without activation.
for %%D in ("%PY_CMD%") do set "PY_ROOT=%%~dpD"
if exist "%PY_ROOT%Library\bin" set "PATH=%PY_ROOT%;%PY_ROOT%Library\bin;%PY_ROOT%Scripts;%PATH%"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
chcp 65001 >nul

echo [1/2] Python: %PY_CMD%
"%PY_CMD%" -c "import uvicorn" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] uvicorn cannot be imported by this interpreter:
    echo         %PY_CMD%
    echo         Repair the environment, install the offline wheels, or point
    echo         win7-python.txt to the correct python.exe.
    echo.
    echo         Repair command:
    echo         "%PY_CMD%" scripts\prepare_win7.py --install-offline --python "%PY_CMD%"
    if "%~1"=="" pause
    exit /b 1
)

echo [2/2] Launching %ROOT%\scripts\win7_launcher.py ...
echo       --check  : environment check only, no server is started.
echo       normal   : the browser opens automatically when the server is ready.
echo       Close this window to stop the application.
echo.

"%PY_CMD%" -B "%ROOT%\scripts\win7_launcher.py" %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
if "%LAUNCH_EXIT%"=="0" exit /b 0

echo.
echo [ERROR] Startup or environment check failed. See the error above.
if "%~1"=="" pause
exit /b %LAUNCH_EXIT%
