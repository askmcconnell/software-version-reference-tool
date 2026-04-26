#Requires -Version 5.1
<#
.SYNOPSIS
    S3C-Tool Windows File-Level Inventory Scanner
    S3C-Tool - Software Security Supply Chain Tool v1.1.0

.DESCRIPTION
    Scans installed programs, file version properties, Windows Store apps,
    .NET frameworks, Python packages, and npm globals.
    Output: s3c_inventory_windows_HOSTNAME_DATE.csv

.NOTES
    HOW TO RUN (avoids ExecutionPolicy block):
        powershell.exe -ExecutionPolicy Bypass -File .\s3c_scan_windows.ps1

    Or from an elevated PowerShell prompt:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\s3c_scan_windows.ps1

    Administrator is NOT required for most scans.
    Without admin, AppX (Windows Store) packages may show current-user only.

.PARAMETER Output
    Path for the output CSV. Default: Desktop\s3c_inventory_windows_DATE.csv

.PARAMETER Quick
    Registry + AppX only. Skips deep Program Files and System32 binary scan.

.PARAMETER NoProgramFiles
    Skip binary scanning inside Program Files folders.

.PARAMETER NoPython
    Skip Python pip package scan.

.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File .\s3c_scan_windows.ps1
    powershell.exe -ExecutionPolicy Bypass -File .\s3c_scan_windows.ps1 -Quick
    powershell.exe -ExecutionPolicy Bypass -File .\s3c_scan_windows.ps1 -Output C:\temp\inventory.csv
#>

[CmdletBinding()]
param(
    [string]$Output = "",
    [switch]$Quick,
    [switch]$NoProgramFiles,
    [switch]$NoPython
)

# Suppress non-critical errors from noisy cmdlets
$ErrorActionPreference = 'SilentlyContinue'

$SVRT_FORMAT_VERSION = '1.0'   # CSV schema version — bump only when columns change
$SCANNER_VERSION     = '1.1.0' # Tool version — follows SemVer (major.minor.patch)
$TODAY               = (Get-Date -Format 'yyyy-MM-dd')
$PLATFORM            = 'windows'

# Output path
if (-not $Output) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $Output  = "$desktop\s3c_inventory_windows_$TODAY.csv"
}

# ==============================================================================
# HELPERS
# ==============================================================================

# PS 5.1-compatible null/empty coalescing (replaces the PS7-only ?? operator)
function NullOr {
    param([object]$Value, [string]$Fallback = '')
    if ($null -eq $Value) { return $Fallback }
    $s = [string]$Value
    if ($s.Trim() -eq '') { return $Fallback }
    return $s
}

function Get-HostnameHash {
    $bytes  = [System.Text.Encoding]::UTF8.GetBytes($env:COMPUTERNAME)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $hash   = $sha256.ComputeHash($bytes)
    return ([BitConverter]::ToString($hash) -replace '-', '').ToLower().Substring(0, 16)
}

function Get-OSVersion {
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        return "$($os.Caption) $($os.Version)"
    } catch {
        return [System.Environment]::OSVersion.VersionString
    }
}

function Get-Arch {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
    switch ($arch) {
        'AMD64'  { return 'x86_64' }
        'ARM64'  { return 'arm64' }
        'x86'    { return 'x86' }
        default  { return $arch }
    }
}

function Get-FileMtime {
    param([string]$Path)
    try {
        return (Get-Item $Path -ErrorAction Stop).LastWriteTime.ToString('yyyy-MM-dd')
    } catch {
        return ''
    }
}

function Get-FileVersion {
    param([string]$Path)
    try {
        $fvi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
        return @{
            ProductVersion = NullOr $fvi.ProductVersion
            FileVersion    = NullOr $fvi.FileVersion
            CompanyName    = NullOr $fvi.CompanyName
            ProductName    = NullOr $fvi.ProductName
        }
    } catch {
        return @{ ProductVersion=''; FileVersion=''; CompanyName=''; ProductName='' }
    }
}

function Extract-Version {
    param([string]$s)
    if (-not $s) { return '' }
    if ($s -match '(\d+\.\d+[\d.\-+a-zA-Z]*)') {
        return $matches[1].Substring(0, [Math]::Min($matches[1].Length, 50))
    }
    return ''
}

function Make-Row {
    param(
        [hashtable]$Base,
        [string]$Filename      = '',
        [string]$Filepath      = '',
        [string]$SoftwareName  = '',
        [string]$Vendor        = '',
        [string]$Version       = '',
        [string]$FileVersion   = '',
        [long]  $FileSizeBytes = 0,
        [string]$FileType      = '',
        [string]$ParentApp     = '',
        [string]$InstallDate   = '',
        [string]$Source        = ''
    )
    $row = $Base.Clone()
    $row['filename']        = $Filename
    $row['filepath']        = $Filepath
    $row['software_name']   = $SoftwareName
    $row['vendor']          = $Vendor
    $row['version']         = $Version
    $row['file_version']    = $FileVersion
    $row['file_size_bytes'] = $FileSizeBytes
    $row['file_type']       = $FileType
    $row['parent_app']      = $ParentApp
    $row['install_date']    = $InstallDate
    $row['source']          = $Source
    return $row
}

# ==============================================================================
# SCANNERS
# ==============================================================================

function Scan-Registry {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning registry (Add/Remove Programs)..." -ForegroundColor Cyan

    $regPaths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )

    $seen  = @{}
    $count = 0

    foreach ($regPath in $regPaths) {
        $items = Get-ItemProperty $regPath -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            $name = NullOr $item.DisplayName
            if (-not $name) { continue }

            $key = $name.ToLower().Trim()
            if ($seen[$key]) { continue }
            $seen[$key] = $true

            $version  = NullOr ($item.DisplayVersion -replace '[^\d.\-a-zA-Z+]', '')
            $vendor   = NullOr $item.Publisher
            $installLocation = NullOr $item.InstallLocation

            $installDate = ''
            if ($item.InstallDate -match '(\d{4})(\d{2})(\d{2})') {
                $installDate = "$($matches[1])-$($matches[2])-$($matches[3])"
            }

            $Rows.Add((Make-Row $Base `
                -Filename      ($name -replace '[\\/:*?"<>|]', '_') `
                -Filepath      ($installLocation -replace '\\$', '') `
                -SoftwareName  $name `
                -Vendor        $vendor `
                -Version       $version `
                -FileVersion   $version `
                -FileSizeBytes 0 `
                -FileType      'package' `
                -ParentApp     '' `
                -InstallDate   $installDate `
                -Source        'registry'
            ))
            $count++
        }
    }
    Write-Host "    -> $count registry entries" -ForegroundColor Gray
}


function Scan-WindowsStore {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning Windows Store (AppX) packages..." -ForegroundColor Cyan
    $count = 0
    try {
        $packages = Get-AppxPackage -ErrorAction Stop
        foreach ($pkg in $packages) {
            $Rows.Add((Make-Row $Base `
                -Filename      (NullOr $pkg.Name) `
                -Filepath      (NullOr $pkg.InstallLocation) `
                -SoftwareName  (NullOr $pkg.Name) `
                -Vendor        (NullOr $pkg.Publisher) `
                -Version       (NullOr ($pkg.Version.ToString())) `
                -FileVersion   (NullOr ($pkg.Version.ToString())) `
                -FileSizeBytes 0 `
                -FileType      'appx' `
                -ParentApp     '' `
                -InstallDate   '' `
                -Source        'appx'
            ))
            $count++
        }
    } catch {
        Write-Host "    (AppX unavailable - run as admin for all-user packages)" -ForegroundColor DarkGray
    }
    Write-Host "    -> $count AppX packages" -ForegroundColor Gray
}


function Scan-ProgramFiles {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning Program Files executables..." -ForegroundColor Cyan

    $dirs = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        $env:ProgramData,
        "$env:LOCALAPPDATA\Programs"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $count = 0
    foreach ($dir in $dirs) {
        $exes = Get-ChildItem -Path $dir -Recurse -Filter '*.exe' -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -gt 0 }
        foreach ($exe in $exes) {
            $fvi  = Get-FileVersion -Path $exe.FullName
            $ver  = Extract-Version ($fvi.ProductVersion -replace ',\s*', '.')
            if (-not $ver) { $ver = Extract-Version ($fvi.FileVersion -replace ',\s*', '.') }
            $name = if ($fvi.ProductName) { $fvi.ProductName } else { $exe.BaseName }

            $Rows.Add((Make-Row $Base `
                -Filename      $exe.Name `
                -Filepath      $exe.FullName `
                -SoftwareName  $name `
                -Vendor        $fvi.CompanyName `
                -Version       $ver `
                -FileVersion   $fvi.FileVersion `
                -FileSizeBytes $exe.Length `
                -FileType      'binary' `
                -ParentApp     '' `
                -InstallDate   (Get-FileMtime $exe.FullName) `
                -Source        'file_version_info'
            ))
            $count++
        }
    }
    Write-Host "    -> $count executables" -ForegroundColor Gray
}


function Scan-SystemBinaries {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning system binaries (System32, SysWOW64)..." -ForegroundColor Cyan

    $dirs = @(
        "$env:SystemRoot\System32",
        "$env:SystemRoot\SysWOW64"
    ) | Where-Object { Test-Path $_ }

    $count = 0
    foreach ($dir in $dirs) {
        $exes = Get-ChildItem -Path $dir -Filter '*.exe' -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -gt 0 }
        foreach ($exe in $exes) {
            $fvi  = Get-FileVersion -Path $exe.FullName
            $ver  = Extract-Version ($fvi.ProductVersion -replace ',\s*', '.')
            if (-not $ver) { $ver = Extract-Version ($fvi.FileVersion -replace ',\s*', '.') }
            $name = if ($fvi.ProductName) { $fvi.ProductName } else { $exe.BaseName }

            $Rows.Add((Make-Row $Base `
                -Filename      $exe.Name `
                -Filepath      $exe.FullName `
                -SoftwareName  $name `
                -Vendor        $fvi.CompanyName `
                -Version       $ver `
                -FileVersion   $fvi.FileVersion `
                -FileSizeBytes $exe.Length `
                -FileType      'binary' `
                -ParentApp     '' `
                -InstallDate   (Get-FileMtime $exe.FullName) `
                -Source        'file_version_info'
            ))
            $count++
        }
    }
    Write-Host "    -> $count system binaries" -ForegroundColor Gray
}


function Scan-PythonPackages {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning Python packages..." -ForegroundColor Cyan
    $count = 0
    foreach ($pipCmd in @('pip3', 'pip', 'python -m pip', 'python3 -m pip')) {
        try {
            $jsonOut = & cmd /c "$pipCmd list --format=json 2>nul" 2>$null
            if (-not $jsonOut) { continue }
            $pkgs = $jsonOut | ConvertFrom-Json -ErrorAction Stop
            foreach ($pkg in $pkgs) {
                $Rows.Add((Make-Row $Base `
                    -Filename      (NullOr $pkg.name) `
                    -Filepath      "pip:$(NullOr $pkg.name)" `
                    -SoftwareName  (NullOr $pkg.name) `
                    -Vendor        '' `
                    -Version       (NullOr $pkg.version) `
                    -FileVersion   (NullOr $pkg.version) `
                    -FileSizeBytes 0 `
                    -FileType      'package' `
                    -ParentApp     'python' `
                    -InstallDate   '' `
                    -Source        'pip'
                ))
                $count++
            }
            if ($count -gt 0) { break }
        } catch { }
    }
    Write-Host "    -> $count Python packages" -ForegroundColor Gray
}


function Scan-NpmPackages {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning npm global packages..." -ForegroundColor Cyan
    $count = 0
    try {
        $jsonOut = & npm list -g --depth=0 --json 2>$null
        if ($jsonOut) {
            $data = $jsonOut | ConvertFrom-Json -ErrorAction Stop
            foreach ($name in $data.dependencies.PSObject.Properties.Name) {
                $ver = NullOr $data.dependencies.$name.version
                $Rows.Add((Make-Row $Base `
                    -Filename      $name `
                    -Filepath      "npm-global:$name" `
                    -SoftwareName  $name `
                    -Vendor        '' `
                    -Version       $ver `
                    -FileVersion   $ver `
                    -FileSizeBytes 0 `
                    -FileType      'package' `
                    -ParentApp     'nodejs' `
                    -InstallDate   '' `
                    -Source        'npm'
                ))
                $count++
            }
        }
    } catch { }
    Write-Host "    -> $count npm global packages" -ForegroundColor Gray
}


function Scan-Winget {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning winget packages..." -ForegroundColor Cyan
    $count = 0
    try {
        # --output json requires winget 1.4+; fall back to table parse if JSON fails
        $jsonOut = & winget list --output json --accept-source-agreements 2>$null
        if ($jsonOut) {
            $data = $jsonOut | ConvertFrom-Json -ErrorAction Stop
            foreach ($pkg in $data) {
                $name = NullOr $pkg.Name
                $id   = NullOr $pkg.Id
                $ver  = NullOr $pkg.Version
                if (-not $name) { $name = $id }
                if (-not $name) { continue }
                $Rows.Add((Make-Row $Base `
                    -Filename      $id `
                    -Filepath      "winget:$id" `
                    -SoftwareName  $name `
                    -Vendor        '' `
                    -Version       $ver `
                    -FileVersion   $ver `
                    -FileSizeBytes 0 `
                    -FileType      'package' `
                    -ParentApp     '' `
                    -InstallDate   '' `
                    -Source        'winget'
                ))
                $count++
            }
        }
    } catch { }
    if ($count -eq 0) {
        # Fallback: parse winget list table output (older winget or if JSON failed)
        try {
            $lines = & winget list --accept-source-agreements 2>$null
            $inData = $false
            foreach ($line in $lines) {
                # Header separator line begins the data block
                if ($line -match '^-{5}') { $inData = $true; continue }
                if (-not $inData) { continue }
                # Columns: Name, Id, Version, [Available], [Source]
                # Split on 2+ spaces to handle column alignment
                $parts = $line -split '\s{2,}'
                if ($parts.Count -ge 3) {
                    $name = $parts[0].Trim()
                    $id   = $parts[1].Trim()
                    $ver  = $parts[2].Trim()
                    if (-not $name) { continue }
                    $Rows.Add((Make-Row $Base `
                        -Filename      $id `
                        -Filepath      "winget:$id" `
                        -SoftwareName  $name `
                        -Vendor        '' `
                        -Version       $ver `
                        -FileVersion   $ver `
                        -FileSizeBytes 0 `
                        -FileType      'package' `
                        -ParentApp     '' `
                        -InstallDate   '' `
                        -Source        'winget'
                    ))
                    $count++
                }
            }
        } catch { }
    }
    Write-Host "    -> $count winget packages" -ForegroundColor Gray
}


function Scan-Chocolatey {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning Chocolatey packages..." -ForegroundColor Cyan
    $count = 0
    try {
        $chocoOut = & choco list --local-only --no-progress 2>$null
        if ($chocoOut) {
            foreach ($line in $chocoOut) {
                # Each line is "PackageName Version" e.g. "git 2.43.0"
                # Skip summary line "N packages installed." and blank lines
                if ($line -match '^(\S+)\s+([\d][^\s]*)$') {
                    $name = $matches[1].Trim()
                    $ver  = $matches[2].Trim()
                    $Rows.Add((Make-Row $Base `
                        -Filename      $name `
                        -Filepath      "choco:$name" `
                        -SoftwareName  $name `
                        -Vendor        '' `
                        -Version       $ver `
                        -FileVersion   $ver `
                        -FileSizeBytes 0 `
                        -FileType      'package' `
                        -ParentApp     '' `
                        -InstallDate   '' `
                        -Source        'choco'
                    ))
                    $count++
                }
            }
        }
    } catch { }
    Write-Host "    -> $count Chocolatey packages" -ForegroundColor Gray
}


function Scan-DotNetFrameworks {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning .NET Framework versions..." -ForegroundColor Cyan
    $ndpPath = 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP'
    $count   = 0

    try {
        Get-ChildItem $ndpPath -Recurse -ErrorAction Stop |
        Where-Object { $_.GetValue('Version') } |
        ForEach-Object {
            $ver  = $_.GetValue('Version')
            $name = "Microsoft .NET Framework $ver"
            $sp   = $_.GetValue('SP')
            if ($sp) { $name += " SP$sp" }
            $Rows.Add((Make-Row $Base `
                -Filename      "dotnet-$ver" `
                -Filepath      "$env:SystemRoot\Microsoft.NET\Framework" `
                -SoftwareName  $name `
                -Vendor        'Microsoft Corporation' `
                -Version       $ver `
                -FileVersion   $ver `
                -FileSizeBytes 0 `
                -FileType      'runtime' `
                -ParentApp     '' `
                -InstallDate   '' `
                -Source        'registry'
            ))
            $count++
        }
    } catch { }

    # .NET 5+ via dotnet CLI
    try {
        $runtimes = & dotnet --list-runtimes 2>$null
        foreach ($line in $runtimes) {
            if ($line -match '(\S+)\s+([\d.]+)\s+') {
                $rtName = $matches[1]
                $rtVer  = $matches[2]
                $Rows.Add((Make-Row $Base `
                    -Filename      "dotnet-$rtName-$rtVer" `
                    -Filepath      "dotnet:$rtName/$rtVer" `
                    -SoftwareName  "Microsoft .NET $rtName" `
                    -Vendor        'Microsoft Corporation' `
                    -Version       $rtVer `
                    -FileVersion   $rtVer `
                    -FileSizeBytes 0 `
                    -FileType      'runtime' `
                    -ParentApp     '' `
                    -InstallDate   '' `
                    -Source        'cli'
                ))
                $count++
            }
        }
    } catch { }

    Write-Host "    -> $count .NET entries" -ForegroundColor Gray
}

function Scan-Firmware {
    param([hashtable]$Base, [System.Collections.Generic.List[hashtable]]$Rows)
    Write-Host "  Scanning BIOS/UEFI firmware..." -ForegroundColor Cyan
    try {
        $bios = Get-WmiObject -Class Win32_BIOS -ErrorAction Stop
        $version = $bios.SMBIOSBIOSVersion
        if (-not $version) { $version = $bios.BIOSVersion -join ' ' }
        $vendor  = $bios.Manufacturer
        $date    = ''
        if ($bios.ReleaseDate) {
            # WMI date format: yyyyMMddHHmmss.ffffff+offset
            try { $date = [Management.ManagementDateTimeConverter]::ToDateTime($bios.ReleaseDate).ToString('yyyy-MM-dd') } catch {}
        }
        if ($version) {
            $Rows.Add((Make-Row $Base `
                -Filename      'bios' `
                -Filepath      'firmware://bios' `
                -SoftwareName  'BIOS / UEFI Firmware' `
                -Vendor        ($vendor -or 'Unknown') `
                -Version       $version `
                -FileVersion   $version `
                -FileSizeBytes 0 `
                -FileType      'firmware' `
                -ParentApp     '' `
                -InstallDate   $date `
                -Source        'wmi'
            ))
            Write-Host "    -> BIOS: $vendor $version" -ForegroundColor Gray
        }
    } catch {
        Write-Host "    -> BIOS scan skipped: $_" -ForegroundColor DarkGray
    }
}


# ==============================================================================
# MAIN
# ==============================================================================

$hostnameHash = Get-HostnameHash
$arch         = Get-Arch
$osVer        = Get-OSVersion

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  S3C-Tool - Windows Inventory Scanner v$SCANNER_VERSION" -ForegroundColor Cyan
Write-Host "  Software Security Supply Chain Tool"                     -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Scanning your installed software..."     -ForegroundColor White
Write-Host "  This will take 1-3 minutes. Please wait." -ForegroundColor Gray
Write-Host ""
Write-Host "  Platform : $osVer ($arch)"              -ForegroundColor Gray
Write-Host "  Saving to: $Output"                     -ForegroundColor Gray
Write-Host ""

$baseRow = @{
    's3c_format_version' = $SVRT_FORMAT_VERSION
    'scan_date'           = $TODAY
    'hostname_hash'       = $hostnameHash
    'platform'            = $PLATFORM
    'arch'                = $arch
    'os_version'          = $osVer
    'filename'            = ''
    'filepath'            = ''
    'software_name'       = ''
    'vendor'              = ''
    'version'             = ''
    'file_version'        = ''
    'file_size_bytes'     = 0
    'file_type'           = ''
    'parent_app'          = ''
    'install_date'        = ''
    'source'              = ''
}

$rows = [System.Collections.Generic.List[hashtable]]::new()

# Phase 1: Firmware
Write-Host "  [1/6] Scanning firmware and OS info..." -ForegroundColor Yellow
Scan-Firmware         -Base $baseRow -Rows $rows

# Phase 2: Registry + Store
Write-Host "  [2/6] Scanning installed programs (registry, Store, .NET)..." -ForegroundColor Yellow
Scan-Registry         -Base $baseRow -Rows $rows
Scan-WindowsStore     -Base $baseRow -Rows $rows
Scan-DotNetFrameworks -Base $baseRow -Rows $rows

# Phase 3: File system
Write-Host "  [3/6] Scanning Program Files and system binaries..." -ForegroundColor Yellow
if (-not $NoProgramFiles -and -not $Quick) {
    Scan-ProgramFiles  -Base $baseRow -Rows $rows
}
if (-not $Quick) {
    Scan-SystemBinaries -Base $baseRow -Rows $rows
}

# Phase 4: Language runtimes
Write-Host "  [4/6] Scanning language runtimes (Python, npm)..." -ForegroundColor Yellow
if (-not $NoPython) {
    Scan-PythonPackages -Base $baseRow -Rows $rows
}
Scan-NpmPackages -Base $baseRow -Rows $rows

# Phase 5: Package managers (winget, Chocolatey)
Write-Host "  [5/6] Scanning package managers (winget, Chocolatey)..." -ForegroundColor Yellow
Scan-Winget      -Base $baseRow -Rows $rows
Scan-Chocolatey  -Base $baseRow -Rows $rows

Write-Host "  [6/6] Deduplicating and writing output..." -ForegroundColor Yellow

# ==============================================================================
# DEDUPLICATE
# ==============================================================================
# The Windows scanner collects from multiple sources. The same software can appear
# in both the registry AND as a binary in Program Files / System32 (e.g. 7-Zip,
# Internet Explorer components). Deduplicate by (software_name, version), keeping
# the highest-priority source: registry/appx/pip/npm > file_version_info.

$sourcePriority = @{
    'registry'          = 0
    'appx'              = 1
    'winget'            = 1
    'choco'             = 1
    'pip'               = 1
    'npm'               = 1
    'cli'               = 1
    'wmi'               = 2
    'file_version_info' = 9
}

$rawCount = $rows.Count
$sorted   = [System.Linq.Enumerable]::OrderBy(
    [System.Collections.Generic.IEnumerable[hashtable]] $rows,
    [Func[hashtable,int]] { param($r) if ($sourcePriority.ContainsKey($r['source'])) { $sourcePriority[$r['source']] } else { 5 } }
)

$seenPairs = @{}
$deduped   = [System.Collections.Generic.List[hashtable]]::new()
foreach ($row in $sorted) {
    $key = ($row['software_name']).ToLower().Trim() + '|' + ($row['version']).ToLower().Trim()
    if ($seenPairs.ContainsKey($key)) { continue }
    $seenPairs[$key] = $true
    $deduped.Add($row)
}
$rows = $deduped
Write-Host "  Deduplication: $rawCount raw → $($rows.Count) unique items (removed $($rawCount - $rows.Count) duplicates)" -ForegroundColor Gray

# ==============================================================================
# WRITE CSV
# ==============================================================================

$fieldNames = @(
    's3c_format_version', 'scan_date', 'hostname_hash', 'platform', 'arch',
    'os_version', 'filename', 'filepath', 'software_name', 'vendor', 'version',
    'file_version', 'file_size_bytes', 'file_type', 'parent_app', 'install_date', 'source'
)

Write-Host ""
Write-Host "Writing $($rows.Count) rows -> $Output" -ForegroundColor Green

$outputDir = Split-Path $Output -Parent
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$csvLines = [System.Collections.Generic.List[string]]::new()
$csvLines.Add(($fieldNames -join ','))

foreach ($row in $rows) {
    $fields = foreach ($f in $fieldNames) {
        $val = if ($null -ne $row[$f]) { [string]$row[$f] } else { '' }
        if ($val -match '[,"\r\n]') {
            '"' + $val.Replace('"', '""') + '"'
        } else {
            $val
        }
    }
    $csvLines.Add(($fields -join ','))
}

[System.IO.File]::WriteAllLines($Output, $csvLines, [System.Text.Encoding]::UTF8)

# ==============================================================================
# SUMMARY
# ==============================================================================

$byType = $rows | Group-Object { $_['file_type'] } | Sort-Object Count -Descending

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  SCAN COMPLETE" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Found    : $($rows.Count) software items" -ForegroundColor White
Write-Host ""
Write-Host "  FILE SAVED TO:" -ForegroundColor Cyan
Write-Host "  $Output" -ForegroundColor White
Write-Host ""
Write-Host "  Next step: upload this file at" -ForegroundColor Gray
Write-Host "  https://askmcconnell.com/s3c" -ForegroundColor Cyan
Write-Host ""

# Open File Explorer to the output folder so they can find the file easily
$outputDir = Split-Path $Output -Parent
if (Test-Path $outputDir) {
    Invoke-Item $outputDir
}

Write-Host "  (File Explorer has been opened to your output folder.)" -ForegroundColor Gray
Write-Host ""
Read-Host "  Press Enter to close this window"
