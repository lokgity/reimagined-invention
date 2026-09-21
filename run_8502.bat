@echo off
rem ============================================================
rem  Start the site-selection agent UI  ->  http://127.0.0.1:8502
rem
rem  Why this file exists: a server started from inside an agent
rem  session gets recycled when that session's turn ends, so the
rem  only reliable way to keep 8502 up is to launch it yourself.
rem
rem  NOTE: keep this file pure ASCII. It lives in a path with
rem  non-ASCII characters, and we dodge the codepage problem by
rem  using %~dp0 (the script's own folder) instead of a literal path.
rem ============================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0.pylibs"
set "PYTHONIOENCODING=utf-8"

echo Starting on http://127.0.0.1:8502  (close this window to stop)
echo.
"C:\Python312\python.exe" -u -m chainlit run src\ui\app_chainlit.py --port 8502 --host 0.0.0.0

echo.
echo Server stopped.
pause
