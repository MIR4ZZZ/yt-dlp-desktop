param([string]$OutputDirectory = 'dist\installer')

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$upstreamVersion = '2026.10.26'
$upstreamRevision = 'f264a6cbd1f630894da0f368df00f8aae50140e0'
$denoVersion = '2.9.8'
$denoSha256 = 'cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf'
$ffmpegName = 'ffmpeg-N-128340-gf80a436ffd-win64-gpl.zip'
$ffmpegSha256 = '91adc75f861c9b1252fe0911fae527763693fa0ffc0ed247cbc9b2be8118b1ce'
$ffmpegTag = 'autobuild-2026-11-02-22-51'
$cache = Join-Path $repoRoot 'build\yt-dlp-ui-cache'
$work = Join-Path $repoRoot 'build\yt-dlp-ui-release'
$python = Join-Path $repoRoot 'build\release-venv\Scripts\python.exe'
$bundle = Join-Path $repoRoot 'dist\yt-dlp-ui'
$output = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
$appVersion = & python -c 'from ui import APP_VERSION; print(APP_VERSION)'

$tagRevision = (& git rev-list -n 1 $upstreamVersion).Trim()
& git merge-base --is-ancestor $tagRevision HEAD
if ($tagRevision -ne $upstreamRevision -or $LASTEXITCODE -ne 0 -or
    (& python -c 'from yt_dlp.version import __version__; print(__version__)').Trim() -ne $upstreamVersion -or
    (git diff $tagRevision --name-only -- yt_dlp) -or
    (git status --porcelain)) {
    throw 'The release must be built from the unmodified yt-dlp 2026.10.26 source tag.'
}
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $repoRoot 'build\release-venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create release environment.' }
}
& $python -m pip install --disable-pip-version-check -e '.[default,gui,pin,pin-curl-cffi]' 'PyInstaller==6.22.0' 'PySide6==6.11.1'
if ($LASTEXITCODE -ne 0) { throw 'Could not install pinned build dependencies.' }
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
if (-not (Test-Path -LiteralPath $iscc)) { throw 'Inno Setup 6 was not found.' }
$curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curl) { throw 'curl.exe was not found.' }
New-Item -ItemType Directory -Force -Path $cache | Out-Null

function Get-PinnedFile {
    param([string]$Path, [string]$Url, [string]$Sha256)
    if (Test-Path -LiteralPath $Path) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() -eq $Sha256) { return }
        Remove-Item -LiteralPath $Path -Force
    }
    $partial = "$Path.part"
    & $curl --fail --location --retry 3 --continue-at - --silent --show-error --output $partial $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant() -ne $Sha256) {
        throw "Hash mismatch for $Url"
    }
    Move-Item -LiteralPath $partial -Destination $Path -Force
}

$denoArchive = Join-Path $cache 'deno-2.9.8.zip'
$ffmpegArchive = Join-Path $cache $ffmpegName
Get-PinnedFile $denoArchive "https://github.com/denoland/deno/releases/download/v$denoVersion/deno-x86_64-pc-windows-msvc.zip" $denoSha256
Get-PinnedFile $ffmpegArchive "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/$ffmpegTag/$ffmpegName" $ffmpegSha256
Get-PinnedFile (Join-Path $cache 'Deno-LICENSE.md') "https://raw.githubusercontent.com/denoland/deno/v$denoVersion/LICENSE.md" 'f62497fffecc0852960c8d3e6934b9db86d16396e9b604072e923892cae3a588'
Get-PinnedFile (Join-Path $cache 'LGPL-3.0.txt') 'https://www.gnu.org/licenses/lgpl-3.0.txt' 'e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118'
Get-PinnedFile (Join-Path $cache 'GPL-3.0.txt') 'https://www.gnu.org/licenses/gpl-3.0.txt' '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'
$ffmpegSource = Join-Path $cache 'FFmpeg-f80a436ffd922aebb6d64824b301884da2cc1ee4.tar.gz'
$ffmpegBuildSource = Join-Path $cache 'FFmpeg-Builds-58084b7cf4984303a34b610ba3ad8f04059d5d89.tar.gz'
Get-PinnedFile $ffmpegSource 'https://github.com/FFmpeg/FFmpeg/archive/f80a436ffd922aebb6d64824b301884da2cc1ee4.tar.gz' '8e59a733200eb5ccbb78d91d4d347eb5bbdc71138b094bcaea27f837bead00fa'
Get-PinnedFile $ffmpegBuildSource 'https://github.com/yt-dlp/FFmpeg-Builds/archive/58084b7cf4984303a34b610ba3ad8f04059d5d89.tar.gz' '875d7364c09411aba18a221c5c3ea16ebb21d7dc1a877a7479297332321d54e2'

foreach ($path in @($work, $bundle)) {
    $resolved = [System.IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($repoRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear outside repository: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $work, $output | Out-Null
$denoExtract = Join-Path $work 'deno'
$ffmpegExtract = Join-Path $work 'ffmpeg'
Expand-Archive -LiteralPath $denoArchive -DestinationPath $denoExtract
Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath $ffmpegExtract
$denoExe = Join-Path $denoExtract 'deno.exe'
$ffmpegExe = Get-ChildItem -LiteralPath $ffmpegExtract -Recurse -File -Filter 'ffmpeg.exe' | Select-Object -First 1
$ffprobeExe = Get-ChildItem -LiteralPath $ffmpegExtract -Recurse -File -Filter 'ffprobe.exe' | Select-Object -First 1
$ffmpegLicense = Get-ChildItem -LiteralPath $ffmpegExtract -Recurse -File | Where-Object Name -match '^(LICENSE|COPYING)(\.txt)?$' | Select-Object -First 1
if (-not (Test-Path -LiteralPath $denoExe) -or -not $ffmpegExe -or -not $ffprobeExe -or -not $ffmpegLicense) {
    throw 'Deno or FFmpeg archive is incomplete or missing a license.'
}
if ((& $denoExe --version | Select-Object -First 1) -ne "deno $denoVersion") { throw 'Unexpected Deno version.' }

& $python devscripts\make_lazy_extractors.py
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare yt-dlp extractors.' }
& $python -m bundle.pyinstaller --clean
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath 'dist\yt-dlp.exe')) { throw 'Source engine build failed.' }
& $python -m PyInstaller --noconfirm --clean yt-dlp-ui.spec
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $bundle 'yt-dlp-ui.exe'))) { throw 'GUI build failed.' }

New-Item -ItemType Directory -Force -Path (Join-Path $bundle 'engine'), (Join-Path $bundle 'tools'), (Join-Path $bundle 'assets'), (Join-Path $bundle 'licenses') | Out-Null
Copy-Item -LiteralPath 'dist\yt-dlp.exe' -Destination (Join-Path $bundle 'engine\yt-dlp.exe')
Copy-Item -LiteralPath $denoExe -Destination (Join-Path $bundle 'engine\deno.exe')
Copy-Item -LiteralPath $ffmpegExe.FullName -Destination (Join-Path $bundle 'tools\ffmpeg.exe')
Copy-Item -LiteralPath $ffprobeExe.FullName -Destination (Join-Path $bundle 'tools\ffprobe.exe')
Copy-Item -LiteralPath 'devscripts\logo.ico' -Destination (Join-Path $bundle 'assets\logo.ico')
Copy-Item -LiteralPath 'LICENSE' -Destination (Join-Path $bundle 'licenses\yt-dlp-LICENSE.txt')
Copy-Item -LiteralPath 'THIRD_PARTY_LICENSES.txt' -Destination (Join-Path $bundle 'licenses\yt-dlp-THIRD-PARTY.txt')
Copy-Item -LiteralPath $ffmpegLicense.FullName -Destination (Join-Path $bundle 'licenses\FFmpeg-LICENSE.txt')
foreach ($name in @('Deno-LICENSE.md', 'LGPL-3.0.txt', 'GPL-3.0.txt')) {
    Copy-Item -LiteralPath (Join-Path $cache $name) -Destination (Join-Path $bundle 'licenses' $name)
}
foreach ($name in @('pyside6', 'pyside6_addons', 'pyside6_essentials', 'shiboken6')) {
    $metadata = Join-Path $repoRoot "build\release-venv\Lib\site-packages\$name-6.11.1.dist-info\METADATA"
    if (-not (Test-Path -LiteralPath $metadata)) { throw "Qt notice missing: $metadata" }
    Copy-Item -LiteralPath $metadata -Destination (Join-Path $bundle 'licenses' "$name-METADATA.txt")
}
Copy-Item -LiteralPath 'ui\THIRD-PARTY-NOTICES.txt' -Destination (Join-Path $bundle 'licenses\THIRD-PARTY-NOTICES.txt')

& $iscc "/DSourceDir=$bundle" "/DOutputDir=$output" "/DAppVersion=$appVersion" 'ui\installer\yt-dlp-ui.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
$installer = Join-Path $output "yt-dlp-desktop-$appVersion-setup.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw 'Installer output missing.' }
$sourceOutput = Join-Path $output 'sources'
New-Item -ItemType Directory -Force -Path $sourceOutput | Out-Null
Copy-Item -LiteralPath $ffmpegSource, $ffmpegBuildSource -Destination $sourceOutput
Copy-Item -LiteralPath 'ui\THIRD-PARTY-SOURCES.txt' -Destination (Join-Path $sourceOutput 'README.txt')
& $python -m pip freeze --disable-pip-version-check | Set-Content -Encoding utf8 (Join-Path $output 'BUILD-DEPENDENCIES.txt')
$manifest = [ordered]@{
    status = 'unsigned preview candidate'
    app_version = $appVersion
    upstream_revision = $upstreamRevision
    gui_revision = (& git rev-parse HEAD).Trim()
    upstream_version = $upstreamVersion
    deno_version = $denoVersion
    ffmpeg_release = $ffmpegTag
    ffmpeg_commit = 'f80a436ffd922aebb6d64824b301884da2cc1ee4'
    ffmpeg_build_revision = '58084b7cf4984303a34b610ba3ad8f04059d5d89'
    ffmpeg_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ffmpegSource).Hash.ToLowerInvariant()
    ffmpeg_build_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ffmpegBuildSource).Hash.ToLowerInvariant()
    build_command = 'powershell -ExecutionPolicy Bypass -File ui\build_windows_exe.ps1'
    installer_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
    binaries = @{}
}
foreach ($path in @((Join-Path $bundle 'engine\yt-dlp.exe'), (Join-Path $bundle 'engine\deno.exe'),
                  (Join-Path $bundle 'tools\ffmpeg.exe'), (Join-Path $bundle 'tools\ffprobe.exe'))) {
    $manifest.binaries[(Split-Path -Leaf $path)] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $output 'RELEASE-MANIFEST.json')
Write-Host "Built candidate: $installer"
