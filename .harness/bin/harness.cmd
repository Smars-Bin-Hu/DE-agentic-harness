@echo off
rem Short command for people (Windows): harness <command> ...
rem Same as: python .harness\engine\cli.py <command> ...  Works from any folder, also through PATH.
where python >nul 2>nul && goto run_python
py "%~dp0..\engine\cli.py" %*
exit /b %errorlevel%
:run_python
python "%~dp0..\engine\cli.py" %*
exit /b %errorlevel%
