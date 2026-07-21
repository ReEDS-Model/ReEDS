# Retrain xgb + ngboost on BOTH layers (overall, then regional), sequentially.
# Usage: pwsh chain_retrain.ps1            # uses paths derived from this script's location
#
# Writes per-run logs to ../logs/ next to this script's study root.

$ErrorActionPreference = "Stop"
$here       = Split-Path -Parent $MyInvocation.MyCommand.Definition
$studyRoot  = Split-Path -Parent $here
$logsDir    = Join-Path $studyRoot "logs"
$chainLog   = Join-Path $logsDir "chain_retrain.log"
$python     = "C:\Users\ychen10\AppData\Local\anaconda3\python.exe"
$trainer    = Join-Path $here "surrogate_ml_models.py"

if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Force -Path $logsDir | Out-Null }

function Log($msg) {
    "$([DateTime]::Now.ToString('HH:mm:ss')) $msg" | Tee-Object -FilePath $chainLog -Append
}

function Run-Layer {
    param([string]$layer, [string]$dataCsv, [string]$outDir)
    $outLog = Join-Path $logsDir "$($layer)_xgb_ngboost.out"
    $errLog = Join-Path $logsDir "$($layer)_xgb_ngboost.err"
    Log "=== $layer : start (data=$dataCsv) ==="
    $proc = Start-Process -FilePath $python `
        -ArgumentList @("-u", $trainer,
                        "--data",       $dataCsv,
                        "--output_dir", $outDir,
                        "--models",     "xgb", "ngboost") `
        -WorkingDirectory $here `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError  $errLog `
        -NoNewWindow -PassThru
    Log "$layer launched (pid $($proc.Id)), waiting..."
    Wait-Process -Id $proc.Id
    Log "=== $layer : done (exit $($proc.ExitCode)) ==="
}

Log "=== chain start ==="
Run-Layer "overall"  (Join-Path $studyRoot "inputs\overall_ml_numeric_merged.csv")  (Join-Path $studyRoot "outputs\overall")
Run-Layer "regional" (Join-Path $studyRoot "inputs\regional_ml_numeric_merged.csv") (Join-Path $studyRoot "outputs\regional")
Log "=== chain done ==="
