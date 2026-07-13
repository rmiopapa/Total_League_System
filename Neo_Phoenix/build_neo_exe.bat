@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo NeoPhoenix EXE Builder
echo ========================================
echo.

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"

if "%PYEXE%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if "%PYEXE%"=="" (
    echo Python was not found.
    echo Install Python, or add Python to PATH, then run this batch again.
    echo.
    pause
    exit /b 1
)

%PYEXE% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed for this Python:
    echo   %PYEXE%
    echo.
    echo Please install it first:
    echo   %PYEXE% -m pip install pyinstaller
    echo.
    pause
    exit /b 1
)

%PYEXE% -c "import customtkinter" >nul 2>nul
if errorlevel 1 (
    echo customtkinter is not installed for this Python:
    echo   %PYEXE%
    echo.
    echo Please install runtime dependencies first:
    echo   %PYEXE% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "Phoenix.ico" (
    echo Phoenix.ico was not found in this folder.
    echo Please place Phoenix.ico next to this batch file.
    echo.
    pause
    exit /b 1
)

echo Cleaning previous build outputs...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "NeoPhoenix.spec" del /q "NeoPhoenix.spec"
if exist "NeoPhoenix_Developer.spec" del /q "NeoPhoenix_Developer.spec"
echo.

echo Building NeoPhoenix.exe...
%PYEXE% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "NeoPhoenix" ^
  --icon "Phoenix.ico" ^
  --add-data "Phoenix.ico;." ^
  --collect-all customtkinter ^
  "neo_ctk_review_window.py"
if errorlevel 1 goto :build_error

echo.
echo Building NeoPhoenix_Developer.exe...
%PYEXE% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "NeoPhoenix_Developer" ^
  --icon "Phoenix.ico" ^
  --add-data "Phoenix.ico;." ^
  --collect-all customtkinter ^
  "neo_ctk_review_window_dev.py"
if errorlevel 1 goto :build_error

echo.
echo Copying runtime folders to dist...
if exist "dist\regression_cases" rmdir /s /q "dist\regression_cases"
xcopy "regression_cases" "dist\regression_cases" /E /I /Y >nul
for %%D in (games html_cache reports urls input) do (
    if not exist "dist\%%D" mkdir "dist\%%D"
)
copy /Y "Phoenix.ico" "dist\Phoenix.ico" >nul
if exist "README_NEO_PHOENIX.md" copy /Y "README_NEO_PHOENIX.md" "dist\README_NEO_PHOENIX.md" >nul

echo.
echo Build completed.
echo   dist\NeoPhoenix.exe
echo   dist\NeoPhoenix_Developer.exe
echo   dist\regression_cases
echo.
pause
exit /b 0

:build_error
echo.
echo Build failed.
echo Please check the messages above.
echo.
pause
exit /b 1
