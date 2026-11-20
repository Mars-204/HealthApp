# Starts the app so your phone can reach it on the same WiFi.
# Run from the activated virtual environment:
#   powershell -ExecutionPolicy Bypass -File .\start_app.ps1
$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress
Write-Host ""
Write-Host "Open one of these on your phone (same WiFi, usually the 192.168.x.x or 10.x.x.x one):"
$ips | ForEach-Object { Write-Host "  http://$($_):8501" }
Write-Host ""
streamlit run app\Home.py --server.address 0.0.0.0 --server.port 8501
