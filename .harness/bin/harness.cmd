@echo off
rem Short command for people and agents (Windows): harness <command> ...
rem Like git, it works on the harness repository the current folder is in: it looks upward from the current folder for
rem .harness\engine\cli.py. Outside every harness repository it uses the repository this script sits in; a copy of this script
rem (in a fixed folder in PATH) has none, so it uses the repository named by HARNESS_HOME, or stops with a message.
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
if exist "%HARNESS_CLI%" goto harness_run
if not defined HARNESS_HOME goto harness_none
if not exist "%HARNESS_HOME%\.harness\engine\cli.py" goto harness_none
set "HARNESS_CLI=%HARNESS_HOME%\.harness\engine\cli.py"
goto harness_run
:harness_none
echo harness: not inside a harness repository. cd into one, or set HARNESS_HOME to one. 1>&2
exit /b 1
:harness_run
where python >nul 2>nul && goto run_python
py "%HARNESS_CLI%" %*
exit /b %errorlevel%
:run_python
python "%HARNESS_CLI%" %*
exit /b %errorlevel%
