try {
  $r = Invoke-WebRequest -Uri 'http://localhost:5007/surrogate_dashboard' -TimeoutSec 60 -UseBasicParsing
  Write-Host "status=$($r.StatusCode) size=$($r.RawContentLength)"
} catch {
  Write-Host "err: $($_.Exception.Message)"
}
Start-Sleep -Seconds 3
Write-Host '--- log tail ---'
Get-Content C:\ReEDS\ReEDS\postprocessing\reedssurr\Stage2\logs\dashboard.log -Tail 20
