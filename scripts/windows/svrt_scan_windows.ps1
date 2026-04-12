#Requires -Version 5.1
<#
.SYNOPSIS
    SVRT Windows File-Level Inventory Scanner
    Ask McConnell's Software Version Reference Tool v1.1

.DESCRIPTION
    Scans installed programs, file version properties, Windows Store apps,
    .NET frameworks, Python packages, and npm globals.
    Output: svrt_inventory_windows_HOSTNAME_DATE.csv

.NOTES
    HOW TO RUN (avoids ExecutionPolicy block):
        powershell.exe -ExecutionPolicy Bypass -File .\svrt_scan_windows.ps1

    Or from an elevated PowerShell prompt:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\svrt_scan_windows.ps1

    Administrator is NOT required for most scans.
    Without admin, AppX (Windows Store) packages may show current-user only.

.PARAMETER Output
    Path for the output CSV. Default: Desktop\svrt_inventory_windows_DATE.csv

.PARAMETER Quick
    Registry + AppX only. Skips deep Program Files and System32 binary scan.

.PARAMETER NoProgramFiles
    Skip binary scanning inside Program Files folders.

.PARAMETER NoPython
    Skip Python pip package scan.

.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File .\svrt_scan_windows.ps1
    powershell.exe -ExecutionPolicy Bypass -File .\svrt_scan_windows.ps1 -Quick
    powershell.exe -ExecutionPolicy Bypass -File .\svrt_scan_windows.ps1 -Output C:\temp\inventory.csv
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

$SVRT_FORMAT_VERSION = '1.0'
$TODAY               = (Get-Date -Format 'yyyy-MM-dd')
$PLATFORM            = 'windows'

# Output path
if (-not $Output) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $Output  = "$desktop\svrt_inventory_windows_$TODAY.csv"
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
        Write-Host "    (AppX unavailable — run as admin for all-user packages)" -ForegroundColor DarkGray
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
                Where-Object { $_.Length -gt 0 } |
                Select-Object -First 500
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
Write-Host "Ask McConnell's Software Version Reference Tool" -ForegroundColor Green
Write-Host "  Windows Inventory Scanner v1.1"
Write-Host "  Platform : $osVer ($arch)"
Write-Host "  Host hash: $hostnameHash"
Write-Host "  Output   : $Output"
Write-Host "  Quick    : $Quick"
Write-Host ""

$baseRow = @{
    'svrt_format_version' = $SVRT_FORMAT_VERSION
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

# Phase 0: Firmware
Write-Host "Phase 0: Firmware" -ForegroundColor Yellow
Scan-Firmware         -Base $baseRow -Rows $rows

# Phase 1: Registry + Store
Write-Host "Phase 1: Registry" -ForegroundColor Yellow
Scan-Registry         -Base $baseRow -Rows $rows
Scan-WindowsStore     -Base $baseRow -Rows $rows
Scan-DotNetFrameworks -Base $baseRow -Rows $rows

# Phase 2: WMI (disabled — Win32_Product can trigger MSI reconfiguration)
if (-not $Quick) {
    Write-Host ""
    Write-Host "Phase 2: WMI/MSI" -ForegroundColor Yellow
    Write-Host "  (Win32_Product scan skipped by default)" -ForegroundColor DarkGray
}

# Phase 3: File system
Write-Host ""
Write-Host "Phase 3: File System" -ForegroundColor Yellow
if (-not $NoProgramFiles -and -not $Quick) {
    Scan-ProgramFiles  -Base $baseRow -Rows $rows
}
if (-not $Quick) {
    Scan-SystemBinaries -Base $baseRow -Rows $rows
}

# Phase 4: Language runtimes
Write-Host ""
Write-Host "Phase 4: Language Runtimes" -ForegroundColor Yellow
if (-not $NoPython) {
    Scan-PythonPackages -Base $baseRow -Rows $rows
}
Scan-NpmPackages -Base $baseRow -Rows $rows

# ==============================================================================
# WRITE CSV
# ==============================================================================

$fieldNames = @(
    'svrt_format_version', 'scan_date', 'hostname_hash', 'platform', 'arch',
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
Write-Host ('-' * 50) -ForegroundColor DarkGray
Write-Host "  Total items : $($rows.Count)" -ForegroundColor White
foreach ($g in $byType) {
    Write-Host ("  {0,-18}: {1}" -f $g.Name, $g.Count)
}
Write-Host ('-' * 50) -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Output: $Output"
Write-Host "  Upload at: https://askmcconnell.com/svrt" -ForegroundColor Green
Write-Host ""
