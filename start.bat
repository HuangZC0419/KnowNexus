@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Manual startup (run these in two separate cmd.exe windows):
rem First, cd /d to the directory containing this start.bat in each window.
rem
rem Window 1 - backend (port 8000):
rem   "%BACKEND_PY%" -m pip install -r backend\requirements.txt   (first time or when dependencies change)
rem   cd /d backend
rem   "%BACKEND_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
rem   API docs: http://localhost:8000/docs
rem
rem Window 2 - frontend (port 5173):
rem   cd /d frontend
rem   npm install                          (first time or when dependencies change)
rem   set VITE_BACKEND_PORT=8000           (match the backend port)
rem   npm run dev -- --port 5173 --host 0.0.0.0
rem   Open http://localhost:5173 in the browser.
rem Keep both windows open; press Ctrl+C in each to stop the services.
rem If a port is occupied, choose another free port and update the frontend
rem VITE_BACKEND_PORT value to match the backend's chosen port.
rem
rem Backend Python runtime lookup order (the first interpreter that can import
rem uvicorn, fastapi, cv2, jieba and rapidocr_onnxruntime wins):
rem   1. BACKEND_PYTHON environment variable (full path to python.exe)
rem   2. backend-python.txt in this folder (one line, no quotes)
rem   3. project virtualenv: .venv or venv (root or backend folder)
rem   4. conda environment CFwin11 (queried with "conda env list", then the
rem      usual Anaconda/Miniconda install locations)
rem   5. conda environment CF (fallback used by earlier development setups)
rem   6. python.exe on PATH
rem Use BACKEND_PYTHON or backend-python.txt to force a specific interpreter.
rem
rem Usage: start.bat                 normal start
rem        start.bat --check         environment check only, no services started
rem        start.bat --no-browser    do not open the browser automatically

set "ROOT=%~dp0"
set "LOCAL_IP=UNKNOWN"
set "PY_CMD="
set "PY_ORIGIN="
set "CHECK_ONLY="
set "NO_BROWSER="

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--check" set "CHECK_ONLY=1"
if /I "%~1"=="--no-browser" set "NO_BROWSER=1"
if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage
shift
goto :parse_args

:args_done
echo.
echo ============================================
echo   OCR Project - Starting services...
echo ============================================
echo.

rem 0. Resolve a Python runtime that owns the backend dependencies
echo [0/6] Locating backend Python runtime...
call :find_python
if errorlevel 1 goto :startup_error

echo         Python      : !PY_CMD!
echo         Source      : !PY_ORIGIN!

if defined CHECK_ONLY (
    "!PY_CMD!" -c "import sys; print('        Version     :', sys.version.split()[0])"
    call :prepare_python_env
    echo         Modules     : uvicorn fastapi cv2 jieba rapidocr_onnxruntime
    echo [OK] Backend Python runtime is ready.
    exit /b 0
)

rem 1. Find free ports
echo [1/6] Scanning free ports...
call :find_free_port 8000 8100 BACKEND_PORT
if errorlevel 1 goto :startup_error

call :find_free_port 5173 5200 FRONTEND_PORT
if errorlevel 1 goto :startup_error

echo         Backend port : !BACKEND_PORT!
echo         Frontend port: !FRONTEND_PORT!

rem 2. Detect local IPv4
echo [2/6] Detecting local network address...
call :detect_local_ip
echo         Local IP     : !LOCAL_IP!

rem 3. Clean any listener that still sits on the selected ports
echo [3/6] Cleaning stale listeners...
call :kill_port !BACKEND_PORT!
call :kill_port !FRONTEND_PORT!

rem 4. Install frontend dependencies if needed
echo [4/6] Checking frontend dependencies...
pushd "%ROOT%frontend" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot enter frontend directory.
    goto :startup_error
)

if not exist "node_modules" (
    echo         Installing npm packages...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd >nul 2>&1
        goto :startup_error
    )
)
popd >nul 2>&1

rem 5. Start backend with the resolved interpreter.
rem    The child process inherits this window's environment, so the conda
rem    env directories are put on PATH only for the launch and then restored.
echo [5/6] Starting backend on port !BACKEND_PORT!...
set "ORIG_PATH=%PATH%"
call :prepare_python_env
start "OCR-Backend" /D "%ROOT%backend" cmd /k ""%PY_CMD%" -m uvicorn app.main:app --host 127.0.0.1 --port !BACKEND_PORT!"
set "PATH=%ORIG_PATH%"
timeout /t 3 /nobreak >nul

rem 6. Start frontend
echo [6/6] Starting frontend on port !FRONTEND_PORT!...
start "OCR-Frontend" cmd /k "title OCR-Frontend ^&^& cd /d %ROOT%frontend ^&^& set VITE_BACKEND_PORT=!BACKEND_PORT! ^&^& npx vite --port !FRONTEND_PORT! --host 0.0.0.0"
timeout /t 3 /nobreak >nul

rem 7. Open browser
if not defined NO_BROWSER start "" "http://localhost:!FRONTEND_PORT!"

echo.
echo ============================================
echo   Startup complete.
echo.
echo   Local URL : http://localhost:!FRONTEND_PORT!
if /I not "!LOCAL_IP!"=="UNKNOWN" (
    echo   LAN URL   : http://!LOCAL_IP!:!FRONTEND_PORT!
)
echo.
echo   Backend API: http://localhost:!BACKEND_PORT!/docs
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
exit /b 0

:usage
echo Usage: start.bat [--check] [--no-browser]
echo   --check       check the backend Python runtime only
echo   --no-browser  do not open the browser automatically
exit /b 0

:startup_error
echo.
echo Startup aborted.
pause
exit /b 1

rem ---------------------------------------------------------------
rem :find_python - set PY_CMD / PY_ORIGIN to a usable interpreter.
rem Returns errorlevel 1 when nothing can import the backend modules.
rem ---------------------------------------------------------------
:find_python
set "PY_CMD="
set "PY_ORIGIN="

if defined BACKEND_PYTHON (
    if exist "%BACKEND_PYTHON%" (
        call :try_python "%BACKEND_PYTHON%" "BACKEND_PYTHON"
        if defined PY_CMD exit /b 0
    ) else (
        echo [WARN] BACKEND_PYTHON points to a missing file:
        echo        %BACKEND_PYTHON%
    )
)

if exist "%ROOT%backend-python.txt" (
    set "PY_FILE_VALUE="
    set /p PY_FILE_VALUE=<"%ROOT%backend-python.txt"
    if defined PY_FILE_VALUE set "PY_FILE_VALUE=!PY_FILE_VALUE:"=!"
    if defined PY_FILE_VALUE (
        if exist "!PY_FILE_VALUE!" (
            call :try_python "!PY_FILE_VALUE!" "backend-python.txt"
            if defined PY_CMD exit /b 0
        ) else (
            echo [WARN] backend-python.txt points to a missing file:
            echo        !PY_FILE_VALUE!
        )
    )
)

call :try_python "%ROOT%.venv\Scripts\python.exe" "project .venv"
if defined PY_CMD exit /b 0
call :try_python "%ROOT%venv\Scripts\python.exe" "project venv"
if defined PY_CMD exit /b 0
call :try_python "%ROOT%backend\.venv\Scripts\python.exe" "backend\.venv"
if defined PY_CMD exit /b 0
call :try_python "%ROOT%backend\venv\Scripts\python.exe" "backend\venv"
if defined PY_CMD exit /b 0

call :try_conda_env CFwin11
if defined PY_CMD exit /b 0
call :try_conda_env CF
if defined PY_CMD exit /b 0

for /f "delims=" %%P in ('where python 2^>nul') do (
    call :try_python "%%P" "python on PATH"
    if defined PY_CMD exit /b 0
)

echo.
echo [ERROR] No Python interpreter with the backend dependencies was found.
echo.
echo         Point start.bat at an interpreter, using one of:
echo           - set BACKEND_PYTHON=^<full path to python.exe^>
echo           - save that path as one line in backend-python.txt
echo           - create a project virtualenv in .venv
echo           - install the backend packages into conda env CFwin11:
echo               conda run -n CFwin11 python -m pip install -r "%ROOT%backend\requirements.txt"
echo.
exit /b 1

rem ---------------------------------------------------------------
rem :try_python <python.exe> <label>
rem Sets PY_CMD / PY_ORIGIN when the interpreter can import the backend
rem modules. Prints one warning line when it exists but dependencies are
rem missing, so the source of the failure is visible.
rem ---------------------------------------------------------------
:try_python
set "CANDIDATE=%~1"
if not exist "%CANDIDATE%" exit /b 0
"%CANDIDATE%" -c "import uvicorn, fastapi, multipart, cv2, numpy, jieba, rapidocr_onnxruntime, openpyxl, xlrd, chardet" >nul 2>&1
if errorlevel 1 (
    echo [WARN] %~2: missing backend dependencies
    echo        %CANDIDATE%
    echo        repair: "%CANDIDATE%" -m pip install -r "%ROOT%backend\requirements.txt"
    exit /b 0
)
set "PY_CMD=%CANDIDATE%"
set "PY_ORIGIN=%~2"
exit /b 0

rem ---------------------------------------------------------------
rem :try_conda_env <env-name>
rem Resolves a conda environment through "conda env list" first, then
rem through the usual Anaconda/Miniconda install locations.
rem ---------------------------------------------------------------
:try_conda_env
set "TARGET_ENV=%~1"
set "CONDA_ENV_PY="

if defined CONDA_EXE (
    for /f "tokens=1,*" %%A in ('"%CONDA_EXE%" env list 2^>nul') do (
        if /I "%%A"=="!TARGET_ENV!" set "CONDA_ENV_PY=%%B\python.exe"
    )
)

if not defined CONDA_ENV_PY (
    for %%D in (
        "E:\Anaconda"
        "C:\ProgramData\Anaconda3"
        "C:\ProgramData\Miniconda3"
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\miniconda3"
        "D:\Anaconda3"
        "F:\anaconda2024.06"
    ) do (
        if not defined CONDA_ENV_PY if exist "%%~D\envs\!TARGET_ENV!\python.exe" set "CONDA_ENV_PY=%%~D\envs\!TARGET_ENV!\python.exe"
    )
)

if defined CONDA_ENV_PY call :try_python "!CONDA_ENV_PY!" "conda env !TARGET_ENV!"
exit /b 0

rem ---------------------------------------------------------------
rem :prepare_python_env
rem Makes the selected interpreter find its DLLs when invoked directly
rem (without conda activation): prepend the env root, Library\bin and
rem Scripts, and clear PYTHONHOME / PYTHONPATH.
rem ---------------------------------------------------------------
:prepare_python_env
for %%D in ("%PY_CMD%") do set "PY_BIN_DIR=%%~dpD"
for %%D in ("%PY_BIN_DIR%..") do set "PY_ROOT_DIR=%%~fD"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PATH=%PY_BIN_DIR%;%PATH%"
if exist "%PY_ROOT_DIR%\Library\bin" set "PATH=%PY_ROOT_DIR%;%PY_ROOT_DIR%\Library\bin;%PY_ROOT_DIR%\Scripts;%PATH%"
exit /b 0

:find_free_port
set "%~3="
set "CURRENT_PORT=%~1"
set "MAX_PORT=%~2"

:find_free_port_loop
netstat -ano 2>nul | findstr /R /C:":!CURRENT_PORT! " | findstr /I "LISTENING" >nul 2>&1
if errorlevel 1 (
    set "%~3=!CURRENT_PORT!"
    exit /b 0
)

set /a CURRENT_PORT+=1
if !CURRENT_PORT! GTR !MAX_PORT! (
    echo [ERROR] No free port in range %~1-%~2.
    exit /b 1
)
goto :find_free_port_loop

:detect_local_ip
set "LOCAL_IP=UNKNOWN"
for /f "tokens=2 delims=:" %%A in ('ipconfig 2^>nul ^| findstr /I "IPv4"') do (
    for /f "tokens=* delims= " %%B in ("%%A") do (
        set "IP_CANDIDATE=%%B"
        if /I not "!IP_CANDIDATE:~0,7!"=="127.0.0" (
            set "LOCAL_IP=!IP_CANDIDATE!"
            exit /b 0
        )
    )
)
exit /b 0

:kill_port
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /R /C:":%~1 " ^| findstr /I "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)
exit /b 0
