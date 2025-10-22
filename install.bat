@echo off
REM ==============================
REM Python Virtual Environment Setup Script
REM ==============================

REM Go to home directory (optional if already there)
cd /d %~dp0

echo Creating Python virtual environment...
python -m venv venv

IF NOT EXIST venv\Scripts\activate (
    echo Failed to create virtual environment. Exiting.
    exit /b 1
)

echo Upgrading pip...
call venv\Scripts\activate
python -m pip install --upgrade pip

echo Cloning py-doc-generator repo...
mkdir libs 2>nul
git clone https://bitbucket.org/grepx/py-doc-generator.git libs\py-doc-generator

echo Installing py-doc-generator dependencies...
call venv\Scripts\activate
pip install -r libs\py-doc-generator\requirements.txt

echo Installing py-doc-generator in editable mode...
call venv\Scripts\activate
pip install -e libs\py-doc-generator

echo Installing main project dependencies...
call venv\Scripts\activate
pip install --no-cache-dir -r requirements.txt

echo Running Alembic migrations if configured...
cd backend
IF EXIST alembic (
    call ..\venv\Scripts\activate
    alembic upgrade head
) ELSE (
    echo Alembic not configured, skipping migrations.
)

echo.
echo ======= SETUP COMPLETE =======
pause
