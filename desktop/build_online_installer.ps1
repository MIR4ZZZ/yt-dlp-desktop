param([Parameter(Mandatory=$true)][string]$PayloadUrl)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$version = '1.3.0-preview.1'
$prefix = "https://github.com/MIR4ZZZ/yt-dlp-desktop/releases/download/v$version/"
if (-not $PayloadUrl.StartsWith($prefix, [StringComparison]::Ordinal) -or -not $PayloadUrl.EndsWith("yt-dlp-desktop-$version-payload.zip", [StringComparison]::Ordinal)) {
    throw "Payload URL must be the versioned public GitHub Release asset under $prefix"
}
$output = Join-Path $root 'dist\tauri-preview'
$manifest = Get-Content -LiteralPath (Join-Path $output "yt-dlp-desktop-$version-manifest.json") -Raw | ConvertFrom-Json
$payload = Join-Path $output "yt-dlp-desktop-$version-payload.zip"
if (-not (Test-Path -LiteralPath $payload) -or (Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.payload_sha256) { throw 'Local payload hash changed.' }
$download = Join-Path $output 'anonymous-download-check.zip'
try {
    & curl.exe --fail --location --retry 2 --silent --show-error --output $download $PayloadUrl
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.payload_sha256) { throw 'Anonymous release download failed or hash mismatched.' }
} finally { if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download -Force } }
$mb = [Math]::Round($manifest.payload_bytes / 1000000, 1)
"This online setup downloads a $mb MB app archive after you click Install. The archive is checked against a fixed SHA-256 hash before extraction. Internet access is required. This public preview is unsigned." |
    Set-Content -LiteralPath 'desktop\installer\download-notice.txt' -Encoding ascii
$iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
& $iscc "/DPayloadUrl=$PayloadUrl" "/DPayloadHash=$($manifest.payload_sha256)" "/DPayloadBytes=$($manifest.payload_bytes)" "/DPayloadExpandedBytes=$($manifest.payload_expanded_bytes)" 'desktop\installer\online.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$setup = Join-Path $output "yt-dlp-desktop-$version-online-setup.exe"
if ((Get-Item -LiteralPath $setup).Length -ge 20000000) { throw 'Installer exceeds the hard 20,000,000-byte limit.' }
Write-Host "Installer: $setup ($((Get-Item -LiteralPath $setup).Length) bytes; SHA-256 $((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()))"
