@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SOLUTION=%SCRIPT_DIR%Model Texture Tool.sln"

set "MSBUILD_EXE="
set "DOTNET_EXE="

if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe" set "MSBUILD_EXE=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if not defined MSBUILD_EXE if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" set "MSBUILD_EXE=%ProgramFiles%\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
if not defined MSBUILD_EXE if exist "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe" set "MSBUILD_EXE=%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if not defined DOTNET_EXE if exist "%ProgramFiles%\dotnet\dotnet.exe" set "DOTNET_EXE=%ProgramFiles%\dotnet\dotnet.exe"
if not defined DOTNET_EXE if exist "%ProgramFiles(x86)%\dotnet\dotnet.exe" set "DOTNET_EXE=%ProgramFiles(x86)%\dotnet\dotnet.exe"

echo Building Python backend dependencies...
if defined MSBUILD_EXE (
    "%MSBUILD_EXE%" "%SOLUTION%" /p:Configuration=Release /t:Build
    if errorlevel 1 exit /b %errorlevel%
) else (
    if defined DOTNET_EXE (
        "%DOTNET_EXE%" build "%SOLUTION%" -c Release
        if errorlevel 1 exit /b %errorlevel%
    ) else (
        echo MSBuild.exe or dotnet.exe was not found.
        exit /b 1
    )
)

echo.
echo Python vendor folder updated:
echo %SCRIPT_DIR%..\Python\vendor

endlocal
