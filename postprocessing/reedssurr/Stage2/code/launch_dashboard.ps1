# Launch the ReEDS-Proxy Bokeh dashboard.
# If the server is already running on port 5006, just opens the browser.
# Otherwise starts a Bokeh server in a visible cmd window (so you can see
# logs and close it to stop the dashboard), waits for it to be ready, then
# opens the browser to http://localhost:5007/reeds_proxy.
#
# This script is invoked by ../Open Dashboard.bat (double-click target).

$ErrorActionPreference = "Stop"
$here       = Split-Path -Parent $MyInvocation.MyCommand.Definition
$studyRoot  = Split-Path -Parent $here
$bokehExe   = "C:\Users\ychen10\AppData\Local\anaconda3\envs\reeds2\Scripts\bokeh.exe"
$dashScript = Join-Path $here "reeds_proxy.py"
# Stage 2 uses port 5007 so it can run alongside Stage 1 (5006) without clashing.
$port       = 5007
$url        = "http://localhost:$port/reeds_proxy"

if (-not (Test-Path $bokehExe)) {
    Write-Host "ERROR: bokeh.exe not found at $bokehExe" -ForegroundColor Red
    Write-Host "Edit launch_dashboard.ps1 to point at your bokeh install."
    Read-Host "Press Enter to close"
    exit 1
}
if (-not (Test-Path $dashScript)) {
    Write-Host "ERROR: dashboard script not found at $dashScript" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$listening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Bokeh server already running on port $port (pid $($listening[0].OwningProcess)). Opening browser..." -ForegroundColor Green
} else {
    Write-Host "Starting Bokeh server on port $port in a new window..." -ForegroundColor Yellow
    Write-Host "Close that window (or press Ctrl+C in it) to stop the dashboard." -ForegroundColor Yellow

    # Launch bokeh in a visible cmd window so the user can see logs and close
    # it to stop the server. ``cmd /k`` keeps the window open even if bokeh
    # exits, so any crash message stays readable.
    $cmdLine = ('title ReEDS-Proxy - close this window to stop the server' +
                ' && "{0}" serve "{1}" --port {2}' +
                ' --allow-websocket-origin=localhost:{2}' +
                ' --allow-websocket-origin=127.0.0.1:{2}') -f $bokehExe, $dashScript, $port
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $cmdLine) | Out-Null

    # Wait up to ~20s for the port to come up
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            $ready = $true
            break
        }
    }
    if ($ready) {
        Write-Host "Server ready. Opening browser..." -ForegroundColor Green
    } else {
        Write-Host "WARNING: server did not start within 20s. Check the bokeh window for errors." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
}

Start-Process $url
Start-Sleep -Seconds 2  # give browser a moment to launch before window closes
