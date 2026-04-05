@echo off
setlocal
pushd "%~dp0"

set "PYTHON_EXE=%PYTHON_EXE%"
if defined PYTHON_EXE goto validate_python

for %%P in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
) do (
    if exist %%~fP (
        set "PYTHON_EXE=%%~fP"
        goto validate_python
    )
)

for /f "delims=" %%P in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%P"
    goto validate_python
)

echo Could not find a standard Python installation.
echo Install Python 3.11+ with tkinter support, or set PYTHON_EXE manually.
popd
exit /b 1

:validate_python
"%PYTHON_EXE%" -c "import sys, tkinter; print(sys.executable)" >nul 2>nul
if errorlevel 1 (
    echo The detected Python does not include tkinter.
    echo Use a regular CPython installation and try again.
    popd
    exit /b 1
)

echo Using Python: "%PYTHON_EXE%"
"%PYTHON_EXE%" -m pip install -r requirements-build.txt
if errorlevel 1 (
    popd
    exit /b 1
)

if exist build rd /s /q build
if exist dist rd /s /q dist

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "model_texture_tool.spec"
if errorlevel 1 (
    popd
    exit /b 1
)

echo.
echo Build complete:
echo "%CD%\dist\Model Texture Tool.exe"
popd
exit /b 0
