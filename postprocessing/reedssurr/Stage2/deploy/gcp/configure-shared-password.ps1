[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$ModelBucket,

    [string]$Region = "us-central1",
    [string]$Service = "reeds-proxy",
    [string]$ArtifactRepository = "reeds-proxy",
    [string]$PasswordSecret = "reedssurr-password-hash",
    [string]$AdminPasswordSecret = "reeds-proxy-admin-password-hash",
    [string]$CookieSecret = "reedssurr-cookie-secret",
    [switch]$KeepPrivate
)

$ErrorActionPreference = "Stop"
$iterations = 600000
$runtimeAccount = "reedssurr-dashboard@$ProjectId.iam.gserviceaccount.com"
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

function ConvertFrom-SecureValue {
    param([Security.SecureString]$Value)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function New-RandomBytes {
    param([int]$Count)
    $bytes = New-Object byte[] $Count
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return $bytes
}

function ConvertTo-Hex {
    param([byte[]]$Bytes)
    return (($Bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Ensure-Secret {
    param([string]$Name)
    if (-not (Test-GcloudResource secrets describe $Name --project=$ProjectId)) {
        Invoke-Gcloud secrets create $Name --project=$ProjectId --replication-policy=automatic
    }
}

function Add-SecretVersion {
    param([string]$Name, [string]$Value)
    # gcloud reads the value from stdin, so it never appears in the command line.
    $Value | & $gcloud secrets versions add $Name --project=$ProjectId --data-file=-
    if ($LASTEXITCODE -ne 0) {
        throw "Could not add a version to Secret Manager secret '$Name'."
    }
}

$activeAccount = & $gcloud auth list --filter=status:ACTIVE --format="value(account)"
if ($LASTEXITCODE -ne 0 -or -not $activeAccount) {
    throw "No active gcloud account. Run 'gcloud auth login' first."
}

foreach ($resourceCheck in @(
    @{ Label = "model bucket"; Arguments = @("storage", "buckets", "describe", "gs://$ModelBucket", "--project=$ProjectId") },
    @{ Label = "Artifact Registry repository"; Arguments = @("artifacts", "repositories", "describe", $ArtifactRepository, "--project=$ProjectId", "--location=$Region") },
    @{ Label = "runtime service account"; Arguments = @("iam", "service-accounts", "describe", $runtimeAccount, "--project=$ProjectId") }
)) {
    $checkArguments = $resourceCheck.Arguments
    if (-not (Test-GcloudResource @checkArguments)) {
        throw "The $($resourceCheck.Label) is missing. Run bootstrap.ps1 first."
    }
}

Write-Host "Choose a shared dashboard password (at least 12 characters)." -ForegroundColor Cyan
$securePassword = Read-Host "Shared password" -AsSecureString
$secureConfirmation = Read-Host "Confirm password" -AsSecureString
$plainPassword = $null
$plainConfirmation = $null
$passwordHash = $null
try {
    $plainPassword = ConvertFrom-SecureValue $securePassword
    $plainConfirmation = ConvertFrom-SecureValue $secureConfirmation
    if ($plainPassword.Length -lt 12) {
        throw "The shared password must contain at least 12 characters."
    }
    if ($plainPassword -cne $plainConfirmation) {
        throw "The two passwords do not match."
    }

    $salt = New-RandomBytes 24
    $passwordBytes = [Text.Encoding]::UTF8.GetBytes($plainPassword)
    $derive = New-Object Security.Cryptography.Rfc2898DeriveBytes(
        $passwordBytes,
        $salt,
        $iterations,
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        $digest = $derive.GetBytes(32)
    }
    finally {
        $derive.Dispose()
    }
    $passwordHash = "pbkdf2_sha256`$$iterations`$$(ConvertTo-Hex $salt)`$$(ConvertTo-Hex $digest)"
}
finally {
    $plainPassword = $null
    $plainConfirmation = $null
    $securePassword.Dispose()
    $secureConfirmation.Dispose()
}

Invoke-Gcloud config set project $ProjectId
Invoke-Gcloud services enable secretmanager.googleapis.com run.googleapis.com cloudbuild.googleapis.com

Ensure-Secret $PasswordSecret
Add-SecretVersion $PasswordSecret $passwordHash
$passwordHash = $null

# Keep deployment repeatable before admin access is configured. The sentinel
# value cannot authenticate, but it gives Cloud Run a valid secret version.
Ensure-Secret $AdminPasswordSecret
$enabledAdminVersion = & $gcloud secrets versions list $AdminPasswordSecret --project=$ProjectId --filter="state=ENABLED" --limit=1 --format="value(name)"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect Secret Manager secret '$AdminPasswordSecret'."
}
$enabledAdminVersion = ($enabledAdminVersion | Select-Object -First 1)
if (-not $enabledAdminVersion) {
    Add-SecretVersion $AdminPasswordSecret "disabled"
}

Ensure-Secret $CookieSecret
$enabledCookieVersion = & $gcloud secrets versions list $CookieSecret --project=$ProjectId --filter="state=ENABLED" --limit=1 --format="value(name)"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect Secret Manager secret '$CookieSecret'."
}
$enabledCookieVersion = ($enabledCookieVersion | Select-Object -First 1)
if (-not $enabledCookieVersion) {
    $cookieValue = [Convert]::ToBase64String((New-RandomBytes 48))
    Add-SecretVersion $CookieSecret $cookieValue
    $cookieValue = $null
}

foreach ($secretName in @($PasswordSecret, $AdminPasswordSecret, $CookieSecret)) {
    Invoke-Gcloud secrets add-iam-policy-binding $secretName --project=$ProjectId --member="serviceAccount:$runtimeAccount" --role=roles/secretmanager.secretAccessor
}

$substitutions = "_REGION=$Region,_SERVICE=$Service,_ARTIFACT_REPOSITORY=$ArtifactRepository,_MODEL_BUCKET=$ModelBucket,_RUNTIME_SERVICE_ACCOUNT=$runtimeAccount,_PASSWORD_SECRET=$PasswordSecret,_ADMIN_PASSWORD_SECRET=$AdminPasswordSecret,_COOKIE_SECRET=$CookieSecret"
Invoke-Gcloud builds submit $repoRoot --project=$ProjectId --config=$cloudBuildFile --ignore-file=$gcloudIgnoreFile --substitutions=$substitutions

$serviceUrl = (& $gcloud run services describe $Service --project=$ProjectId --region=$Region --format="value(status.url)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $serviceUrl) {
    throw "The deployment completed, but the Cloud Run URL could not be read."
}

if (-not $KeepPrivate) {
    Invoke-Gcloud run services add-iam-policy-binding $Service --project=$ProjectId --region=$Region --member=allUsers --role=roles/run.invoker
    Write-Host "Password-protected dashboard published:" -ForegroundColor Green
}
else {
    Write-Host "Password authentication deployed; Cloud Run remains private:" -ForegroundColor Green
}
Write-Host "$serviceUrl/reeds_proxy"
Write-Host "The password itself was not uploaded or saved; only its one-way hash is in Secret Manager."
