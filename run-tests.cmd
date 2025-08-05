@echo off
setlocal enabledelayedexpansion

:: Set console to use UTF-8 encoding
chcp 65001 >nul

echo Respondr Test Runner
echo ===================
echo.

echo Checking prerequisites...
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python not found. Please install Python 3.8 or later.
    exit /b 1
) else (
    for /f "tokens=*" %%i in ('python --version') do echo [√] Using %%i
)

:: Check Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Node.js not found. Please install Node.js 14 or later.
    exit /b 1
) else (
    for /f "tokens=*" %%i in ('node --version') do echo [√] Using Node.js %%i
)

:: Check project structure
if not exist "backend" (
    echo [X] Backend directory not found.
    exit /b 1
)
if not exist "frontend" (
    echo [X] Frontend directory not found.
    exit /b 1
)
echo [√] Project structure found

:: Check backend virtual environment
if defined VIRTUAL_ENV (
    echo [√] Virtual environment active: %VIRTUAL_ENV%
) else if exist "backend\.venv" (
    echo [!] Virtual environment found but not active. Activating...
    call backend\.venv\Scripts\activate.bat
    echo [√] Virtual environment activated
) else (
    echo [!] No virtual environment found.
)

:: Check backend dependencies
python -c "import fastapi" >nul 2>&1
if %errorlevel% eq 0 (
    echo [√] Backend dependencies installed
) else (
    echo [!] Backend dependencies may need to be installed
)

:: Check backend .env file
if exist "backend\.env" (
    echo [√] Backend .env file found
) else (
    echo [!] Backend .env file not found. Some tests may use default values.
)

:: Check frontend dependencies
if exist "frontend\node_modules" (
    echo [√] Frontend dependencies installed
) else (
    echo [!] Frontend dependencies need to be installed
)

if exist "frontend\package.json" (
    echo [√] Frontend package.json found
) else (
    echo [X] Frontend package.json not found
    exit /b 1
)

echo.
echo [√] All prerequisites met. Starting tests...
echo.

:: Run backend tests
echo Backend Tests
echo -------------
cd backend
python run_tests.py
set backend_result=%errorlevel%
cd ..

if %backend_result% neq 0 (
    echo Backend tests failed!
    set overall_result=1
) else (
    echo All backend tests passed!
    set overall_result=0
)

echo.

:: Run frontend tests
echo Frontend Tests
echo --------------
cd frontend
set CI=true
npm test -- --watchAll=false --ci
set frontend_result=%errorlevel%
cd ..

if %frontend_result% neq 0 (
    echo Frontend tests failed!
    set overall_result=1
) else (
    echo All frontend tests passed!
)

echo.
echo Test Summary
echo ===========

if %backend_result% eq 0 (
    echo Backend Tests: PASSED
) else (
    echo Backend Tests: FAILED
)

if %frontend_result% eq 0 (
    echo Frontend Tests: PASSED
) else (
    echo Frontend Tests: FAILED
)

echo.
if %overall_result% eq 0 (
    echo All tests passed successfully!
) else (
    echo Some tests failed.
)

exit /b %overall_result%
