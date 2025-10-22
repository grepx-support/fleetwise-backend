@echo off
REM ===================================================
REM Fleetwise Backend Setup Script (Windows)
REM ===================================================
cd /d %~dp0
echo.
echo ================================================
echo  Setting up Fleetwise Backend Environment
echo ================================================
REM ---------------------------------------------------
REM 1. Create Python virtual environment
REM ---------------------------------------------------
echo Creating Python virtual environment...
python -m venv venv
IF NOT EXIST venv\Scripts\activate (
    echo Failed to create virtual environment. Exiting.
    exit /b 1
)
REM ---------------------------------------------------
REM 2. Upgrade pip
REM ---------------------------------------------------
echo Upgrading pip...
call venv\Scripts\activate
python -m pip install --upgrade pip
REM ---------------------------------------------------
REM 3. Clone required repositories
REM ---------------------------------------------------
echo Preparing library directory...
mkdir libs 2>nul
echo Cloning py-doc-generator...
git clone https://bitbucket.org/grepx/py-doc-generator.git libs\py-doc-generator
echo Cloning supporting GrepX libraries...
git clone https://grepx-admin@bitbucket.org/grepx/py-web-libs.git libs\py-web-libs
git clone https://grepx-admin@bitbucket.org/grepx/grepx-py-sql-database-libs.git libs\grepx-py-sql-database-libs
git clone https://grepx-admin@bitbucket.org/grepx/py-utils.git libs\py-utils
REM ---------------------------------------------------
REM 4. Install py-doc-generator requirements
REM ---------------------------------------------------
echo Installing py-doc-generator dependencies...
call venv\Scripts\activate
pip install -r libs\py-doc-generator\requirements.txt
REM ---------------------------------------------------
REM 5. Install py-doc-generator in editable mode
REM ---------------------------------------------------
echo Installing py-doc-generator (editable mode)...
call venv\Scripts\activate
pip install -e libs\py-doc-generator
REM ---------------------------------------------------
REM 6. Install other GrepX libraries in editable mode
REM ---------------------------------------------------
echo Installing py-web-libs (editable mode)...
call venv\Scripts\activate
pip install -e libs\py-web-libs
echo Installing grepx-py-sql-database-libs (editable mode)...
call venv\Scripts\activate
pip install -e libs\grepx-py-sql-database-libs
echo Installing py-utils (editable mode)...
call venv\Scripts\activate
pip install -e libs\py-utils
REM ---------------------------------------------------
REM 7. Install main backend dependencies
REM ---------------------------------------------------
echo Installing main project dependencies...
call venv\Scripts\activate
pip install --no-cache-dir -r requirements.txt
REM ---------------------------------------------------
REM 8. Install Firebase dependencies if available
REM ---------------------------------------------------
IF EXIST requirements-firebase.txt (
    echo Installing Firebase dependencies...
    call venv\Scripts\activate
    pip install -r requirements-firebase.txt
) ELSE (
    echo No Firebase requirements found, skipping.
)
REM ---------------------------------------------------
REM 9. Run Alembic migrations from backend directory
REM ---------------------------------------------------
IF EXIST backend\alembic (
    echo Running Alembic migrations from backend directory...
    call venv\Scripts\activate
    cd backend
    alembic upgrade head
    cd ..
) ELSE (
    echo Alembic not configured in backend directory, skipping migrations.
)
echo.
echo ================================================
echo  ✅ Fleetwise Backend Setup Complete
echo ================================================
pause