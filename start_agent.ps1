# ZheLi Site-Selection Agent Launcher (ASCII-only to avoid GBK/UTF-8 mojibake)
# Path 'YaSuo' is built from Unicode codepoints: \u538B + \u7F29
$proj = 'D:\Users\ASUS\Desktop\' + [char]0x538B + [char]0x7F29 + '\site-selection-agent'
Set-Location -LiteralPath $proj
Write-Host '========================================'
Write-Host '  ZheLi Agent -  Zhe Li Xuan Zhi'
Write-Host '  Open browser: http://127.0.0.1:8502'
Write-Host '  Close this window to stop the server'
Write-Host '========================================'
Write-Host ''
& 'C:\Python312\python.exe' -m chainlit run src\ui\app_chainlit.py --port 8502 --host 0.0.0.0
