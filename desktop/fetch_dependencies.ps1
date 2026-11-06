$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cache = Join-Path $root 'build\yt-dlp-ui-cache'
New-Item -ItemType Directory -Force -Path $cache | Out-Null

function Get-PinnedFile([string]$path, [string]$url, [string]$sha256) {
    if (Test-Path -LiteralPath $path) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $sha256) { return }
        throw "Existing dependency differs from its pinned hash: $path"
    }
    $partial = "$path.part"
    & curl.exe --fail --location --retry 3 --silent --show-error --output $partial $url
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha256) { throw "Pinned download failed verification: $url" }
    Move-Item -LiteralPath $partial -Destination $path
}

Get-PinnedFile (Join-Path $cache 'deno-2.9.8.zip') 'https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip' 'cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf'
Get-PinnedFile (Join-Path $root 'build\ffmpeg-shared.zip') 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/autobuild-2026-11-02-22-51/ffmpeg-N-128340-gf80a436ffd-win64-gpl-shared.zip' '9fe93861754224a0c09e41743cbec85633adda10d1b071b608b263a660118dfb'
Get-PinnedFile (Join-Path $root 'build\MicrosoftEdgeWebview2Setup.exe') 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' 'cf2f2445fef0c5c14e372045f84998771eeb8bb01d59be4afd00692fa160082e'
Get-PinnedFile (Join-Path $cache 'Deno-LICENSE.md') 'https://raw.githubusercontent.com/denoland/deno/v2.9.8/LICENSE.md' 'f62497fffecc0852960c8d3e6934b9db86d16396e9b604072e923892cae3a588'
Get-PinnedFile (Join-Path $cache 'GPL-3.0.txt') 'https://www.gnu.org/licenses/gpl-3.0.txt' '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'
Get-PinnedFile (Join-Path $cache 'LGPL-3.0.txt') 'https://www.gnu.org/licenses/lgpl-3.0.txt' 'e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118'
Get-PinnedFile (Join-Path $cache 'FFmpeg-f80a436ffd922aebb6d64824b301884da2cc1ee4.tar.gz') 'https://github.com/FFmpeg/FFmpeg/archive/f80a436ffd922aebb6d64824b301884da2cc1ee4.tar.gz' '8e59a733200eb5ccbb78d91d4d347eb5bbdc71138b094bcaea27f837bead00fa'
Get-PinnedFile (Join-Path $cache 'FFmpeg-Builds-58084b7cf4984303a34b610ba3ad8f04059d5d89.tar.gz') 'https://github.com/yt-dlp/FFmpeg-Builds/archive/58084b7cf4984303a34b610ba3ad8f04059d5d89.tar.gz' '875d7364c09411aba18a221c5c3ea16ebb21d7dc1a877a7479297332321d54e2'
