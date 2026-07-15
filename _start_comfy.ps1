Start-Process -FilePath "D:\Neiro\comfy\ComfyUI\.venv\Scripts\python.exe" -ArgumentList "main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch" -WorkingDirectory "D:\Neiro\comfy\ComfyUI"
Start-Sleep -Seconds 40
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8188/queue" -TimeoutSec 5 -UseBasicParsing
    Write-Output "Ready: $($r.Content)"
} catch {
    Write-Output "Not ready: $_"
}
