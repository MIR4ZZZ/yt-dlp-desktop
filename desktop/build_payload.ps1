$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$version = '1.3.0-preview.1'
$tag = '2026.10.26'
$denoHash = 'cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf'
$ffmpegHash = '9fe93861754224a0c09e41743cbec85633adda10d1b071b608b263a660118dfb'
$webviewHash = 'cf2f2445fef0c5c14e372045f84998771eeb8bb01d59be4afd00692fa160082e'
$cache = Join-Path $root 'build\yt-dlp-ui-cache'
$ffmpegArchive = Join-Path $root 'build\ffmpeg-shared.zip'
$webview = Join-Path $root 'build\MicrosoftEdgeWebview2Setup.exe'
$output = Join-Path $root 'dist\tauri-preview'
$payload = Join-Path $output "yt-dlp-desktop-$version-payload"
$zip = "$payload.zip"
$python = Join-Path $root 'build\release-venv\Scripts\python.exe'
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'fetch_dependencies.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Dependency download or verification failed.' }

function Assert-Hash([string]$path, [string]$expected) {
    if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw "Missing or changed pinned dependency: $path"
    }
}
Assert-Hash (Join-Path $cache 'deno-2.9.8.zip') $denoHash
Assert-Hash $ffmpegArchive $ffmpegHash
Assert-Hash $webview $webviewHash
if ((& git rev-list -n 1 $tag).Trim() -ne 'f264a6cbd1f630894da0f368df00f8aae50140e0' -or
    (git diff $tag --name-only -- yt_dlp) -or (git diff --name-only -- yt_dlp) -or
    (& python -c 'from yt_dlp.version import __version__; print(__version__)').Trim() -ne $tag) {
    throw 'yt-dlp source differs from the pinned stable tag.'
}
if (-not (Test-Path -LiteralPath $python)) {
    & python -m venv (Join-Path $root 'build\release-venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create build Python environment.' }
}
& $python -m pip install --disable-pip-version-check -e '.[default,pin,pin-curl-cffi]' 'PyInstaller==6.22.0'
if ($LASTEXITCODE -ne 0) { throw 'Could not install pinned engine build dependencies.' }
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
& $python devscripts\make_lazy_extractors.py
if ($LASTEXITCODE -ne 0) { throw 'Extractor generation failed.' }
& $python -m bundle.pyinstaller --clean
if ($LASTEXITCODE -ne 0) { throw 'Source-built yt-dlp failed.' }
Push-Location (Join-Path $root 'desktop')
try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend install failed.' }; npm run check; if ($LASTEXITCODE -ne 0) { throw 'Frontend check failed.' }; npm run tauri build -- --no-bundle; if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed.' } }
finally { Pop-Location }

New-Item -ItemType Directory -Force -Path $output | Out-Null
$resolved = [IO.Path]::GetFullPath($payload)
if (-not $resolved.StartsWith(([IO.Path]::GetFullPath($output) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe payload path.' }
if (Test-Path -LiteralPath $payload) { Remove-Item -LiteralPath $payload -Recurse -Force }
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
New-Item -ItemType Directory -Force -Path $payload, (Join-Path $payload 'engine'), (Join-Path $payload 'tools'), (Join-Path $payload 'licenses') | Out-Null
Copy-Item -LiteralPath 'desktop\src-tauri\target\release\yt-dlp-desktop.exe' -Destination $payload
Copy-Item -LiteralPath 'dist\yt-dlp.exe' -Destination (Join-Path $payload 'engine\yt-dlp.exe')
$denoTemp = Join-Path $output 'deno-extract'
if (-not ([IO.Path]::GetFullPath($denoTemp)).StartsWith(([IO.Path]::GetFullPath($output) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe Deno extraction path.' }
if (Test-Path -LiteralPath $denoTemp) { Remove-Item -LiteralPath $denoTemp -Recurse -Force }
Expand-Archive -LiteralPath (Join-Path $cache 'deno-2.9.8.zip') -DestinationPath $denoTemp
Copy-Item -LiteralPath (Join-Path $denoTemp 'deno.exe') -Destination (Join-Path $payload 'engine\deno.exe')
$ffmpegBin = Join-Path $root 'build\ffmpeg-shared-extract\ffmpeg-N-128340-gf80a436ffd-win64-gpl-shared\bin'
if (-not (Test-Path -LiteralPath $ffmpegBin)) { Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath (Join-Path $root 'build\ffmpeg-shared-extract') }
if (-not (Test-Path -LiteralPath (Join-Path $ffmpegBin 'avcodec-63.dll'))) { throw 'Shared FFmpeg DLLs missing.' }
Get-ChildItem -LiteralPath $ffmpegBin -File | Where-Object { $_.Extension -in @('.exe', '.dll') -and $_.Name -ne 'ffplay.exe' } | Copy-Item -Destination (Join-Path $payload 'tools')
Copy-Item -LiteralPath (Join-Path (Split-Path $ffmpegBin -Parent) 'LICENSE.txt') -Destination (Join-Path $payload 'licenses\FFmpeg-LICENSE.txt')
Copy-Item -LiteralPath 'LICENSE' -Destination (Join-Path $payload 'licenses\yt-dlp-LICENSE.txt')
Copy-Item -LiteralPath 'THIRD_PARTY_LICENSES.txt' -Destination (Join-Path $payload 'licenses\yt-dlp-THIRD-PARTY.txt')
Copy-Item -LiteralPath (Join-Path $cache 'Deno-LICENSE.md') -Destination (Join-Path $payload 'licenses\Deno-LICENSE.md')
Copy-Item -LiteralPath (Join-Path $cache 'GPL-3.0.txt') -Destination (Join-Path $payload 'licenses\GPL-3.0.txt')
Copy-Item -LiteralPath (Join-Path $cache 'LGPL-3.0.txt') -Destination (Join-Path $payload 'licenses\LGPL-3.0.txt')
Copy-Item -LiteralPath 'desktop\THIRD-PARTY-NOTICES.txt' -Destination (Join-Path $payload 'licenses\THIRD-PARTY-NOTICES.txt')

$files = Get-ChildItem -LiteralPath $payload -Recurse -File
$expanded = ($files | Measure-Object -Property Length -Sum).Sum
Compress-Archive -Path (Join-Path $payload '*') -DestinationPath $zip -CompressionLevel Optimal
$archive = Get-Item -LiteralPath $zip
$sha = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{ status='local unsigned preview candidate'; app_version=$version; yt_dlp_version=$tag; yt_dlp_revision='f264a6cbd1f630894da0f368df00f8aae50140e0'; gui_revision=(& git rev-parse HEAD).Trim(); deno_version='2.9.8'; ffmpeg_release='autobuild-2026-11-02-22-51'; ffmpeg_shared_archive_sha256=$ffmpegHash; webview_bootstrapper_sha256=$webviewHash; payload_bytes=$archive.Length; payload_expanded_bytes=$expanded; payload_sha256=$sha; build_command='powershell -ExecutionPolicy Bypass -File desktop\build_payload.ps1'; binaries=@{} }
foreach ($file in $files) { $manifest.binaries[$file.FullName.Substring($payload.Length + 1).Replace('\','/')] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $output "yt-dlp-desktop-$version-manifest.json")
Copy-Item -LiteralPath (Join-Path $cache 'FFmpeg-f80a436ffd922aebb6d64824b301884da2cc1ee4.tar.gz'), (Join-Path $cache 'FFmpeg-Builds-58084b7cf4984303a34b610ba3ad8f04059d5d89.tar.gz') -Destination $output
Write-Host "Payload: $zip ($($archive.Length) bytes; SHA-256 $sha)"
