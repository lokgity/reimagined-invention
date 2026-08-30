@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='D:\Users\ASUS\Desktop\'+[char]0x538B+[char]0x7F29+'\site-selection-agent'; Set-Location -LiteralPath $p; Write-Host '=== ZheLi Agent ==='; Write-Host 'Open http://127.0.0.1:8502 in browser'; Write-Host 'Close this window to stop'; Write-Host ''; & 'C:\Python312\python.exe' -m chainlit run src\ui\app_chainlit.py --port 8502 --host 0.0.0.0"
pause
