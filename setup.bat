@echo off
echo ============================================
echo  Amethyst Music Pipeline - Setup
echo ============================================
echo.

echo [1/4] Checking Python installation...
python --version
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python first.
    echo Download from: https://python.org/downloads
    pause
    exit /b 1
)

echo.
echo [2/4] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies!
    pause
    exit /b 1
)

echo.
echo [3/4] Installing dbt...
pip install dbt-postgres
if errorlevel 1 (
    echo ERROR: Failed to install dbt!
    pause
    exit /b 1
)

echo.
echo [4/4] Installing Node.js dependencies for player...
cd amethyst-desktop-player\player
npm install
npm install pg
if errorlevel 1 (
    echo ERROR: Failed to install Node dependencies!
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup complete!
echo ============================================
echo.
echo Next steps:
echo 1. Make sure PostgreSQL is running
echo 2. Create music_db database in pgAdmin
echo 3. Run the schema SQL to create tables
echo 4. Open Jupyter: jupyter notebook
echo 5. Run notebooks in order:
echo    - load_sources.ipynb
echo    - spotify.ipynb
echo    - youtube.ipynb
echo 6. Run dbt: cd music_pipeline\music_pipeline ^&^& dbt run
echo 7. Start player: cd amethyst-desktop-player\player ^&^& npm start
echo.
pause
