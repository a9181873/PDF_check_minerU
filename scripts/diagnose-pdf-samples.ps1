param(
  [string]$Image = "pdf-check-backend:latest",
  [string]$Downloads = "$env:USERPROFILE\Downloads",
  [string]$ProductDm = "",
  [switch]$SkipReport
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ProductDm) {
  $ProductDm = Join-Path $repo ([string]::Concat([char]0x5546, [char]0x54C1, 'DM'))
}

$dockerArgs = @(
  "run", "--rm",
  "-e", "PYTHONIOENCODING=utf-8",
  "-v", "${repo}:/repo:ro",
  "-w", "/repo/backend"
)

$roots = @()
if (Test-Path -LiteralPath $Downloads) {
  $dockerArgs += @("-v", "${Downloads}:/samples/downloads:ro")
  $roots += "/samples/downloads"
}
if (Test-Path -LiteralPath $ProductDm) {
  $dockerArgs += @("-v", "${ProductDm}:/samples/product_dm:ro")
  $roots += "/samples/product_dm"
}

if (-not $roots) {
  throw "No sample roots found. Check Downloads/ProductDm paths."
}

$dockerArgs += @($Image, "python", "scripts/diagnose_pdf_samples.py")
if ($SkipReport) {
  $dockerArgs += "--skip-report"
}
$dockerArgs += $roots

docker @dockerArgs
