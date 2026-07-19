$ErrorActionPreference = "Stop"

$RepositoryArchive = if ($env:BHAJAN_INSTALL_SOURCE) {
    $env:BHAJAN_INSTALL_SOURCE
}
else {
    "https://github.com/rithamnatani/bhajan/archive/refs/heads/main.zip"
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Add-UserPath([string]$Directory) {
    if (-not $Directory -or -not (Test-Path -LiteralPath $Directory)) {
        return
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($userPath -split ";" | Where-Object { $_ })
    if ($entries -notcontains $Directory) {
        $newPath = (@($Directory) + $entries) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    }
    if (($env:Path -split ";") -notcontains $Directory) {
        $env:Path = "$Directory;$env:Path"
    }
}

function Find-WinGetExecutable([string]$PackagePattern, [string]$Executable) {
    $root = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (-not (Test-Path -LiteralPath $root)) {
        return $null
    }

    return Get-ChildItem -LiteralPath $root -Directory -Filter $PackagePattern `
        -ErrorAction SilentlyContinue |
        ForEach-Object {
            Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Filter $Executable `
                -ErrorAction SilentlyContinue
        } |
        Select-Object -First 1 -ExpandProperty FullName
}

function Resolve-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $localUv = Join-Path $HOME ".local\bin\uv.exe"
    if (Test-Path -LiteralPath $localUv) {
        Add-UserPath (Split-Path -Parent $localUv)
        return $localUv
    }

    return Find-WinGetExecutable "astral-sh.uv_*" "uv.exe"
}

function Install-PortableFfmpeg {
    $installRoot = Join-Path $env:LOCALAPPDATA "bhajan\ffmpeg"
    $archive = Join-Path $env:TEMP "bhajan-ffmpeg.zip"

    Write-Host "Downloading a portable FFmpeg build..."
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    Invoke-WebRequest `
        -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
        -OutFile $archive

    Write-Host "Extracting FFmpeg..."
    Remove-Item -LiteralPath $installRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $installRoot -Force
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue

    $ffmpegPath = Get-ChildItem -LiteralPath $installRoot -Recurse -File `
        -Filter "ffmpeg.exe" | Select-Object -First 1 -ExpandProperty FullName
    $ffprobePath = Get-ChildItem -LiteralPath $installRoot -Recurse -File `
        -Filter "ffprobe.exe" | Select-Object -First 1 -ExpandProperty FullName
    if (-not $ffmpegPath -or -not $ffprobePath) {
        throw "The portable FFmpeg archive did not contain ffmpeg.exe and ffprobe.exe."
    }

    Add-UserPath (Split-Path -Parent $ffmpegPath)
    return @{
        Ffmpeg = $ffmpegPath
        Ffprobe = $ffprobePath
    }
}

Write-Host "Installing bhajan and its system dependencies..." -ForegroundColor Cyan

$winget = Get-Command winget -ErrorAction SilentlyContinue
$uv = Resolve-Uv
if (-not $uv) {
    if ($winget) {
        Write-Host "Installing uv..."
        & winget install --id astral-sh.uv --exact `
            --accept-package-agreements --accept-source-agreements --silent
    }
    Refresh-ProcessPath
    $uv = Resolve-Uv
    if (-not $uv) {
        Write-Host "Installing uv with Astral's official installer..."
        Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression
        Refresh-ProcessPath
        $uv = Resolve-Uv
    }
}

if (-not $uv) {
    throw "uv was installed but could not be located. Open a new PowerShell window and run this installer again."
}
Add-UserPath (Split-Path -Parent $uv)

$existingFfmpeg = Find-WinGetExecutable "Gyan.FFmpeg_*" "ffmpeg.exe"
if ($existingFfmpeg) {
    Add-UserPath (Split-Path -Parent $existingFfmpeg)
}
$existingFfprobe = Find-WinGetExecutable "Gyan.FFmpeg_*" "ffprobe.exe"

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if (-not $ffmpeg -and $existingFfmpeg) {
    $ffmpeg = $existingFfmpeg
}
if (-not $ffprobe -and $existingFfprobe) {
    $ffprobe = $existingFfprobe
}
if (-not $ffmpeg -or -not $ffprobe) {
    if ($winget) {
        Write-Host "Installing FFmpeg with WinGet..."
        & winget install --id Gyan.FFmpeg --exact `
            --accept-package-agreements --accept-source-agreements --silent
        Refresh-ProcessPath

        $ffmpegPath = Find-WinGetExecutable "Gyan.FFmpeg_*" "ffmpeg.exe"
        if ($ffmpegPath) {
            Add-UserPath (Split-Path -Parent $ffmpegPath)
        }
        $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
        $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    }

    if (-not $ffmpeg -or -not $ffprobe) {
        $portable = Install-PortableFfmpeg
        $ffmpeg = $portable.Ffmpeg
        $ffprobe = $portable.Ffprobe
    }
}

if (-not $ffmpeg -or -not $ffprobe) {
    throw "FFmpeg could not be installed."
}

Write-Host "Installing bhajan as an isolated uv tool..."
& $uv tool install --force --python 3.12 $RepositoryArchive
if ($LASTEXITCODE -ne 0) {
    throw "uv could not install bhajan."
}

& $uv tool update-shell | Out-Null
$toolBin = (& $uv tool dir --bin | Out-String).Trim()
Add-UserPath $toolBin

$bhajan = Join-Path $toolBin "bhajan.exe"
if (-not (Test-Path -LiteralPath $bhajan)) {
    throw "bhajan was installed, but its executable was not found in $toolBin."
}

Write-Host ""
Write-Host "bhajan installed successfully." -ForegroundColor Green
& $bhajan --version
Write-Host ""
Write-Host 'Try: bhajan "INSERT_LINK_HERE" --gui -v'
Write-Host "If this window cannot find bhajan by name, open a new PowerShell window."
