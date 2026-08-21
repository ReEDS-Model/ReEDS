[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$ModelBucket,

    [string]$Region = "us-central1",
    [string]$Service = "reeds-proxy",
    [string]$ArtifactRepository = "reeds-proxy",
    [string]$ModelsRoot = "C:\Users\ychen10\OneDrive - NREL\Project 18 - ReEDS Surrogate\reedssurr_models"
)

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $here "..\..\..\..\..")).Path
$cloudBuildFile = Join-Path $here "cloudbuild.yaml"
$gcloudIgnoreFile = Join-Path $here ".gcloudignore"
$gcloudCommand = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
if ($gcloudCommand) {
    $gcloud = $gcloudCommand.Source
}
else {
    $gcloudCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        (Join-Path $env:ProgramFiles "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd")
    )
    $gcloud = $gcloudCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $gcloud) {
    throw "Google Cloud CLI was not found. Install it or add gcloud.cmd to PATH."
}
$runtimeAccountName = "reedssurr-dashboard"
$runtimeAccount = "$runtimeAccountName@$ProjectId.iam.gserviceaccount.com"

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed: $($Arguments -join ' ')"
    }
}

function Test-GcloudResource {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $gcloud @Arguments *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

$requiredModelDirs = @(
    (Join-Path $ModelsRoot "Stage2\overall\models"),
    (Join-Path $ModelsRoot "Stage2\regional\models")
)
foreach ($dir in $requiredModelDirs) {
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        throw "Required model directory not found: $dir"
    }
}

$activeAccount = & $gcloud auth list --filter=status:ACTIVE --format="value(account)"
if ($LASTEXITCODE -ne 0 -or -not $activeAccount) {
    throw "No active gcloud account. Run 'gcloud auth login' first."
}

Invoke-Gcloud config set project $ProjectId
Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com

if (-not (Test-GcloudResource storage buckets describe "gs://$ModelBucket" --project=$ProjectId)) {
    Invoke-Gcloud storage buckets create "gs://$ModelBucket" --project=$ProjectId --location=$Region --uniform-bucket-level-access
}

if (-not (Test-GcloudResource artifacts repositories describe $ArtifactRepository --project=$ProjectId --location=$Region)) {
    Invoke-Gcloud artifacts repositories create $ArtifactRepository --project=$ProjectId --location=$Region --repository-format=docker
}

if (-not (Test-GcloudResource iam service-accounts describe $runtimeAccount --project=$ProjectId)) {
    Invoke-Gcloud iam service-accounts create $runtimeAccountName --project=$ProjectId --display-name="ReEDS-Proxy dashboard"
}

$storageBindingApplied = $false
for ($attempt = 1; $attempt -le 12; $attempt++) {
    try {
        Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$ModelBucket" --member="serviceAccount:$runtimeAccount" --role=roles/storage.objectViewer
        $storageBindingApplied = $true
        break
    }
    catch {
        if ($attempt -eq 12) {
            throw
        }
        Write-Host "Waiting for the new service account to propagate (attempt $attempt/12)..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
}
if (-not $storageBindingApplied) {
    throw "Could not grant the runtime service account access to the model bucket."
}

$buildAccount = (& $gcloud builds get-default-service-account --project=$ProjectId).Trim()
if ($LASTEXITCODE -ne 0 -or -not $buildAccount) {
    throw "Could not resolve the default Cloud Build service account."
}
foreach ($role in @("roles/run.admin", "roles/artifactregistry.writer", "roles/logging.logWriter")) {
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$buildAccount" --role=$role --condition=None
}
Invoke-Gcloud iam service-accounts add-iam-policy-binding $runtimeAccount --project=$ProjectId --member="serviceAccount:$buildAccount" --role=roles/iam.serviceAccountUser

$env:CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED = "True"
$env:CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD = "50MiB"
$env:CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE = "16MiB"
Invoke-Gcloud storage rsync --recursive $requiredModelDirs[0] "gs://$ModelBucket/Stage2/overall/models"
Invoke-Gcloud storage rsync --recursive $requiredModelDirs[1] "gs://$ModelBucket/Stage2/regional/models"

$passwordScript = Join-Path $here "configure-shared-password.ps1"
& $passwordScript -ProjectId $ProjectId -ModelBucket $ModelBucket -Region $Region -Service $Service -ArtifactRepository $ArtifactRepository
