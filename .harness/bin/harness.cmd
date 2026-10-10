@echo off
rem Short command for people and agents (Windows): harness <command> ...
rem Like git, it works on the harness repository the current folder is in: it looks upward from the current folder for
rem .harness\engine\cli.py. Outside every harness repository it uses the copy this script belongs to (also through PATH).
setlocal
set "HARNESS_DIR=%CD%"
:harness_up
if exist "%HARNESS_DIR%\.harness\engine\cli.py" goto harness_found
for %%I in ("%HARNESS_DIR%\..") do set "HARNESS_PARENT=%%~fI"
if /i "%HARNESS_PARENT%"=="%HARNESS_DIR%" goto harness_own
set "HARNESS_DIR=%HARNESS_PARENT%"
goto harness_up
:harness_found
set "HARNESS_CLI=%HARNESS_DIR%\.harness\engine\cli.py"
goto harness_run
:harness_own
set "HARNESS_CLI=%~dp0..\engine\cli.py"
:harness_run
where python >nul 2>nul && goto run_python
py "%HARNESS_CLI%" %*
exit /b %errorlevel%
:run_python
python "%HARNESS_CLI%" %*
exit /b %errorlevel%
