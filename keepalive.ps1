$url = "https://tgpost-bot-l4wq.onrender.com/keepalive"
try {
    $r = Invoke-WebRequest -Uri $url -TimeoutSec 30 -UseBasicParsing
    Write-Host "$(Get-Date -Format 'HH:mm:ss') OK $($r.StatusCode)"
} catch {
    Write-Host "$(Get-Date -Format 'HH:mm:ss') FAIL: $_"
}
