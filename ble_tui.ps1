<#
  ble_tui.ps1 - orchestrator TUI for the WAMBLE toolkit and BLE-Exploits PoCs.

  The PowerShell counterpart of ble_tui.sh, for native use on Windows (it also
  runs under PowerShell 7 on macOS/Linux). A keyboard-driven menu (arrow keys /
  j,k / Enter / q) that launches the same Python tools -- no Bluetooth logic
  lives here. Authorized/educational use only; the exploit PoCs are for devices
  you own or have written permission to test.

  Usage:  .\ble_tui.ps1      (from PowerShell, in the WAMBLE folder)
  If script execution is blocked:  Set-ExecutionPolicy -Scope Process RemoteSigned
#>

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# --- paths -----------------------------------------------------------------
$Here = $PSScriptRoot
if ([string]::IsNullOrEmpty($Here)) { $Here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Src = Join-Path $Here 'src'
$Captures = Join-Path $Src 'wamble/exploits/captures'
# Scans are saved inside the project (scans/) rather than a temp dir, so they are
# easy to find, reuse and clear from the TUI ("Delete saved scans").
$ScansDir = Join-Path $Here 'scans'
try { New-Item -ItemType Directory -Force -Path $ScansDir | Out-Null } catch {}
# Make the wamble package importable for `python -m wamble.*`, installed or not.
if ($env:PYTHONPATH) { $env:PYTHONPATH = "$Src$([IO.Path]::PathSeparator)$env:PYTHONPATH" }
else { $env:PYTHONPATH = $Src }

# --- python: prefer local venv, else python / py ---------------------------
$Py = $null
$venvWin  = Join-Path $Here '.venv\Scripts\python.exe'
$venvUnix = Join-Path $Here '.venv/bin/python'
if (Test-Path $venvWin) { $Py = $venvWin }
elseif (Test-Path $venvUnix) { $Py = $venvUnix }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Py = 'python' }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $Py = 'py' }

# --- box-drawing glyphs (PS 5.1 + 7 compatible) ----------------------------
$TL = [char]0x256D; $TR = [char]0x256E; $BL = [char]0x2570; $BR = [char]0x256F
$HZ = [char]0x2500; $VT = [char]0x2502; $LT = [char]0x251C; $RT = [char]0x2524
$ARROW = [char]0x25BA; $UPTRI = [char]0x25B2; $DNTRI = [char]0x25BC

# Single source of truth: read the package version so this launcher never drifts
# from pyproject.toml / src/wamble/__init__.py. $Py and PYTHONPATH are set above.
$Version = '?'
if ($Py) {
    try {
        $v = (& $Py -c 'import wamble; print(wamble.__version__)' 2>$null)
        if ($v) { $Version = "$v".Trim() }
    } catch {}
}
$MinW = 40   # narrowest the panel is allowed to get
$MaxW = 72   # widest it will grow, so lines stay readable on a big terminal
# Layout globals recomputed each frame by Update-Layout, so the UI follows a
# terminal resize: Cols/Lines hold the terminal size, W the panel width, Pad the
# left margin that centers the panel, and Compact/BannerH the banner size.
$Cols = 80; $Lines = 24; $W = $MaxW; $Pad = ''; $Compact = $false; $BannerH = 9

# Recompute the responsive layout from the current console size.
function Update-Layout {
    try { $script:Cols = [Console]::WindowWidth } catch { $script:Cols = 80 }
    try { $script:Lines = [Console]::WindowHeight } catch { $script:Lines = 24 }
    if ($script:Cols -lt 1) { $script:Cols = 80 }
    if ($script:Lines -lt 1) { $script:Lines = 24 }
    $w = $MaxW
    if ($w -gt $script:Cols - 2) { $w = $script:Cols - 2 }
    if ($w -lt $MinW) { $w = $MinW }
    if ($w -gt $script:Cols) { $w = $script:Cols }   # pathologically narrow terminal
    $script:W = $w
    $lp = [int](($script:Cols - $w) / 2)
    if ($lp -lt 0) { $lp = 0 }
    $script:Pad = ' ' * $lp
    # Drop the wombat on a short or narrow terminal so the list keeps its room.
    if ($script:Lines -ge 20 -and $script:Cols -ge 24) { $script:Compact = $false; $script:BannerH = 9 }
    else { $script:Compact = $true; $script:BannerH = 2 }
}

# Print a line centered across the whole console width.
function Write-Centered {
    param([string]$Text, [System.ConsoleColor]$Color = [System.ConsoleColor]::Gray)
    $lp = [int](($script:Cols - $Text.Length) / 2)
    if ($lp -lt 0) { $lp = 0 }
    Write-Host ((' ' * $lp) + $Text) -ForegroundColor $Color
}

function Show-Banner {
    Clear-Host
    Update-Layout
    if ($script:Compact) {
        Write-Centered "WAMBLE v$Version  Windows And Mac BLE" Cyan
        Write-Host ''
        return
    }
    # The wombat mascot, centered as a block so its shape is preserved. Drawn
    # squat and broad with a big nose and small rounded ears, the way a wombat is.
    $art = @('   __      __   ', '  /  \____/  \  ', ' / o        o \ ', '(     (__)     )', ' \            / ', "  '-||----||-'  ")
    $artW = 16
    $alp = [int](($script:Cols - $artW) / 2); if ($alp -lt 0) { $alp = 0 }
    $ap = ' ' * $alp
    foreach ($line in $art) { Write-Host ($ap + $line) -ForegroundColor Cyan }
    Write-Centered "WAMBLE  v$Version" Cyan
    Write-Centered 'Windows And Mac BLE toolkit and PoCs' DarkGray
    Write-Host ''
}

function Write-Edge($left, $right) {
    Write-Host ($script:Pad + [string]$left + ([string]$HZ * ($script:W - 2)) + [string]$right) -ForegroundColor Cyan
}

function Write-Row {
    param([string]$Text, [string]$Style = 'normal')
    $inner = ' ' + $Text
    if ($inner.Length -gt ($script:W - 2)) { $inner = $inner.Substring(0, $script:W - 2) }
    else { $inner = $inner.PadRight($script:W - 2) }
    Write-Host -NoNewline ($script:Pad + [string]$VT) -ForegroundColor Cyan
    switch ($Style) {
        'sel'   { Write-Host -NoNewline $inner -ForegroundColor Black -BackgroundColor Cyan }
        'title' { Write-Host -NoNewline $inner -ForegroundColor Magenta }
        default { Write-Host -NoNewline $inner }
    }
    Write-Host ([string]$VT) -ForegroundColor Cyan
}

# Returns the selected index, or -1 for q / back.
function Show-Menu {
    param([string]$Title, [string[]]$Options)
    $sel = 0; $top0 = 0
    $n = $Options.Count
    try { [Console]::CursorVisible = $false } catch {}
    while ($true) {
        Show-Banner    # redraws the banner and refreshes the layout each frame
        # Fit the list to the terminal: show a scrolling window around the
        # selection rather than letting a long list overflow.
        $avail = $script:Lines - $script:BannerH - 8
        if ($avail -lt 3) { $avail = 3 }
        $win = $n; if ($win -gt $avail) { $win = $avail }
        if ($sel -lt $top0) { $top0 = $sel }
        if ($sel -ge $top0 + $win) { $top0 = $sel - $win + 1 }
        if ($top0 -gt $n - $win) { $top0 = $n - $win }
        if ($top0 -lt 0) { $top0 = 0 }

        Write-Edge $TL $TR
        Write-Row $Title 'title'
        Write-Edge $LT $RT
        if ($top0 -gt 0) { Write-Row ("  $UPTRI $top0 more above") 'normal' }
        for ($i = $top0; $i -lt $top0 + $win; $i++) {
            if ($i -eq $sel) { Write-Row ([string]$ARROW + ' ' + $Options[$i]) 'sel' }
            else { Write-Row ('  ' + $Options[$i]) 'normal' }
        }
        if ($top0 + $win -lt $n) { Write-Row ("  $DNTRI $($n - $top0 - $win) more below") 'normal' }
        Write-Edge $BL $BR
        Write-Host ''
        Write-Host ($script:Pad + ' Up/Down or j/k - Enter select - q back') -ForegroundColor DarkGray
        $key = [Console]::ReadKey($true)
        switch ($key.Key) {
            'UpArrow'   { $sel = (($sel - 1) + $n) % $n }
            'DownArrow' { $sel = ($sel + 1) % $n }
            'K'         { $sel = (($sel - 1) + $n) % $n }
            'J'         { $sel = ($sel + 1) % $n }
            'Enter'     { try { [Console]::CursorVisible = $true } catch {}; return $sel }
            'Q'         { try { [Console]::CursorVisible = $true } catch {}; return -1 }
        }
    }
}

# --- input + run helpers ---------------------------------------------------
function Ask {
    param([string]$Prompt, [string]$Default = '')
    if ($Default -ne '') {
        $v = Read-Host "$Prompt [$Default]"
        if ([string]::IsNullOrWhiteSpace($v)) { return $Default } else { return $v }
    }
    return Read-Host $Prompt
}

function Confirm-Yes {
    param([string]$Prompt)
    $a = Read-Host "$Prompt (y/N)"
    return ($a -match '^[yY]')
}

function Invoke-Tool {
    # CmdArgs[0] is a module spec (e.g. 'wamble.scan'); the tool runs as a module.
    param([string[]]$CmdArgs)
    try { [Console]::CursorVisible = $true } catch {}
    Show-Banner
    $full = @('-m') + $CmdArgs
    Write-Host (' > ' + $Py + ' ' + ($full -join ' ')) -ForegroundColor Green
    Write-Host ''
    & $Py @full
    Write-Host ''
    Read-Host '[done] Press Enter to return' | Out-Null
}

function Get-Device { return (Ask 'Target device (name substring or address)') }

# Map a tool to its module: toolkit tools are wamble.<name>, exploits are
# wamble.exploits.<name>.
function Tool([string]$name) { return "wamble.$name" }
function Exp([string]$name)  { return "wamble.exploits.$name" }

# A new scan gets a timestamped file in scans/, so results are kept and clearable.
function New-ScanFile { return (Join-Path $ScansDir ("scan-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))) }

# Delete the saved scan JSONs from scans/.
function Clear-Scans {
    Show-Banner
    $files = @(Get-ChildItem -Path $ScansDir -Filter 'scan-*.json' -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) {
        Write-Host " No saved scans in $ScansDir" -ForegroundColor Yellow
        Read-Host | Out-Null; return
    }
    Write-Host " Saved scans in ${ScansDir}:" -ForegroundColor White
    $files | ForEach-Object { Write-Host "   $($_.Name)" }
    Write-Host ''
    if (Confirm-Yes "Delete these $($files.Count) scan file(s)?") {
        $files | Remove-Item -Force -ErrorAction SilentlyContinue
        Write-Host " Deleted $($files.Count) scan file(s)." -ForegroundColor Green
    } else {
        Write-Host ' Cancelled.' -ForegroundColor DarkGray
    }
    Read-Host | Out-Null
}

# --- toolkit menu ----------------------------------------------------------
function Show-ToolkitMenu {
    while ($true) {
        $i = Show-Menu 'WAMBLE Toolkit (gatttool/BlueZ-style)' @(
            'Scan advertisements        (scan_ble)',
            'Watch advertisements live  (watch_ble)',
            'Enumerate GATT + reads     (enum_ble)',
            'Interactive GATT client    (gatt_cli)',
            'Find UUID                  (gatt_find)',
            'Battery level              (gatt_battery)',
            'Device information         (read_device_info)',
            'ATT MTU                    (gatt_mtu)',
            'Connection params (--get)  (gatt_params)',
            'Connection benchmark       (bench)',
            'Signal / range monitor     (range)',
            'Pair / unpair              (pair)',
            'Delete saved scans         (clear scans/)',
            'Back')
        switch ($i) {
            0 { $s = Ask 'Scan seconds' '8'; $out = New-ScanFile; Invoke-Tool @((Tool 'scan'), '-t', $s, '--write-to', $out) }
            1 { $t = Ask 'Timeout seconds' '20'; Invoke-Tool @((Tool 'watch'), '--timeout', $t) }
            2 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'enum'), $d, '--readable') } }
            3 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'interactive'), $d) } }
            4 { $d = Get-Device; if ($d) { $u = Ask 'UUID substring'; Invoke-Tool @((Tool 'find'), $d, $u) } }
            5 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'battery'), $d) } }
            6 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'device_info'), $d) } }
            7 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'mtu'), $d) } }
            8 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'params'), $d, '--get') } }
            9 { $d = Get-Device; if ($d) { Invoke-Tool @((Tool 'bench'), $d) } }
            10 { $d = Get-Device; if ($d) { $t = Ask 'Timeout seconds (blank=until Ctrl-C)' '30'; if ($t) { Invoke-Tool @((Tool 'range'), $d, '--timeout', $t) } else { Invoke-Tool @((Tool 'range'), $d) } } }
            11 { $d = Get-Device; if ($d) { $c = Ask 'Encrypted char UUID to trigger pairing on macOS (blank = none)'; if ($c) { Invoke-Tool @((Tool 'pair'), $d, '--char', $c) } else { Invoke-Tool @((Tool 'pair'), $d) } } }
            12 { Clear-Scans }
            default { return }
        }
    }
}

# --- exploit menu (authorized / own-device) --------------------------------
function Require-Auth([string]$dev) {
    Show-Banner
    if (Confirm-Yes "Authorized: do you own '$dev' / have permission?") { return $true }
    Write-Host "`n Not authorized - aborting." -ForegroundColor Yellow
    Read-Host | Out-Null
    return $false
}

function Show-ExploitMenu {
    while ($true) {
        $i = Show-Menu 'BLE-Exploits  -  authorized / own-device only' @(
            'Unauthenticated GATT harvest   (recon, read-only)',
            'Security-posture assessment    (posture, read-only)',
            'Notification capture           (notify, read-only)',
            'Passive advertisement harvest  (adv, no connection)',
            'LED control PoC                (led, gated)',
            'Capture-replay / forgery       (replay, gated)',
            'Persistence across reboot      (persistence, gated)',
            'Device-name deface to PWNED!   (deface, gated)',
            'GATT write fuzzer              (fuzz, gated)',
            'Back')
        switch ($i) {
            0 { $d = Get-Device; if ($d) { Invoke-Tool @((Exp 'recon_dump'), $d) } }
            1 { $d = Get-Device; if ($d) { Invoke-Tool @((Exp 'posture_scan'), $d) } }
            2 { $d = Get-Device; if ($d) { $s = Ask 'Capture seconds' '12'; Invoke-Tool @((Exp 'notify_capture'), $d, '--duration', $s) } }
            3 { $d = Get-Device; if ($d) { $s = Ask 'Listen seconds' '25'; Invoke-Tool @((Exp 'adv_harvest'), $d, '--timeout', $s) } }
            4 { $d = Get-Device; if ($d -and (Require-Auth $d)) { Invoke-Tool @((Exp 'led_unauth_control'), $d, '--authorized', '--demo') } }
            5 { $d = Get-Device; if ($d -and (Require-Auth $d)) { $c = Ask 'Capture file to replay (path)'; if ($c) { Invoke-Tool @((Exp 'replay'), $d, '--authorized', '--from-capture', $c) } } }
            6 { $d = Get-Device; if ($d -and (Require-Auth $d)) { Show-PersistMenu $d } }
            7 { $d = Get-Device; if ($d -and (Require-Auth $d)) { Show-DefaceMenu $d } }
            8 { $d = Get-Device; if ($d -and (Require-Auth $d)) { Show-FuzzMenu $d } }
            default { return }
        }
    }
}

function Show-PersistMenu([string]$dev) {
    $i = Show-Menu "Persistence phase for $dev" @('arm (set state, then power-cycle)', 'verify (after reboot)', 'Back')
    switch ($i) {
        0 { $hex = Ask 'Value to persist, hex (known-valid!)'; if ($hex) { Invoke-Tool @((Exp 'persistence_test'), 'arm', $dev, '--authorized', '--write', $hex) } }
        1 { Invoke-Tool @((Exp 'persistence_test'), 'verify', $dev, '--authorized') }
        default { return }
    }
}

function Show-DefaceMenu([string]$dev) {
    $i = Show-Menu "Deface $dev (Device Name -> PWNED!)" @('deface (write PWNED!)', 'restore original name', 'Back')
    switch ($i) {
        0 { Invoke-Tool @((Exp 'deface'), $dev, '--authorized') }
        1 { Invoke-Tool @((Exp 'deface'), $dev, '--authorized', '--restore') }
        default { return }
    }
}

function Show-FuzzMenu([string]$dev) {
    $i = Show-Menu "Fuzz writable characteristics on $dev" @(
        'dry run (list payloads, write nothing)',
        'execute (actually fuzz - can hang the device)',
        'Back')
    switch ($i) {
        0 { Invoke-Tool @((Exp 'gatt_fuzz'), $dev) }
        1 { Invoke-Tool @((Exp 'gatt_fuzz'), $dev, '--authorized', '--execute') }
        default { return }
    }
}

# --- CTF client ------------------------------------------------------------
function Show-CtfMenu {
    Show-Banner
    $dev = Ask 'CTF device name/address' '2b00042f7481c7b056c4b410d28f33cf'
    if (-not $dev) { return }
    $ctf = Tool 'ctf'
    while ($true) {
        $i = Show-Menu "BLE CTF client - target: $dev" @(
            'Enumerate (handles)',
            'Score (read 0x002a)',
            'MTU check (flag 16 reachability)',
            'Read handle',
            'Write hex to handle',
            'Write string to handle',
            'Submit flag string (0x002c)',
            'Listen notify/indicate + trigger',
            'Read-loop (flag 10)',
            'Back')
        switch ($i) {
            0 { Invoke-Tool @($ctf, '-b', $dev, 'enum') }
            1 { Invoke-Tool @($ctf, '-b', $dev, 'score') }
            2 { Invoke-Tool @($ctf, '-b', $dev, 'mtu') }
            3 { $h = Ask 'Handle (e.g. 0x002e)'; if ($h) { Invoke-Tool @($ctf, '-b', $dev, 'read', '-a', $h) } }
            4 { $h = Ask 'Handle'; $v = Ask 'Hex value (e.g. 41)'; if ($h -and $v) { Invoke-Tool @($ctf, '-b', $dev, 'write', '-a', $h, '-n', $v) } }
            5 { $h = Ask 'Handle'; $s = Ask 'String'; if ($h) { Invoke-Tool @($ctf, '-b', $dev, 'writestr', '-a', $h, '-s', $s) } }
            6 { $s = Ask 'Flag string'; if ($s) { Invoke-Tool @($ctf, '-b', $dev, 'submit', '-s', $s) } }
            7 { $h = Ask 'Handle'; $v = Ask 'Trigger hex (blank = none)'
                if ($h) { if ($v) { Invoke-Tool @($ctf, '-b', $dev, 'listen', '-a', $h, '-n', $v) } else { Invoke-Tool @($ctf, '-b', $dev, 'listen', '-a', $h) } } }
            8 { $h = Ask 'Handle' '0x003e'; $c = Ask 'Count' '1001'; Invoke-Tool @($ctf, '-b', $dev, 'readloop', '-a', $h, '-c', $c) }
            default { return }
        }
    }
}

# --- captures viewer -------------------------------------------------------
function Show-Captures {
    if (-not (Test-Path $Captures)) { Show-Banner; Write-Host ' No captures yet.' -ForegroundColor Yellow; Read-Host | Out-Null; return }
    $files = @(Get-ChildItem -Path $Captures -Filter *.json -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($files.Count -eq 0) { Show-Banner; Write-Host ' No captures yet.' -ForegroundColor Yellow; Read-Host | Out-Null; return }
    $names = @($files | ForEach-Object { $_.Name }) + 'Back'
    while ($true) {
        $i = Show-Menu "Evidence captures ($Captures)" $names
        if ($i -lt 0 -or $i -ge $files.Count) { return }
        Invoke-Tool @('-m', 'json.tool', $files[$i].FullName)
    }
}

# --- dependency check ------------------------------------------------------
function Test-Deps {
    if (-not $Py) {
        Show-Banner
        Write-Host ' No Python found (python / py / .venv).' -ForegroundColor Red
        Write-Host "`n Create the venv first:`n" -ForegroundColor DarkGray
        Write-Host "   py -3 -m venv .venv" -ForegroundColor DarkGray
        Write-Host "   .\.venv\Scripts\Activate.ps1" -ForegroundColor DarkGray
        Write-Host "   pip install -r requirements.txt`n" -ForegroundColor DarkGray
        Read-Host 'Press Enter to exit' | Out-Null
        exit 1
    }
    & $Py -c 'import bleak, rich' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Show-Banner
        Write-Host " bleak/rich not available to $Py" -ForegroundColor Red
        Write-Host '   pip install -r requirements.txt' -ForegroundColor DarkGray
        Read-Host 'Press Enter to continue anyway, or Ctrl-C to quit' | Out-Null
    }
}

# --- main ------------------------------------------------------------------
Test-Deps
$running = $true
while ($running) {
    $i = Show-Menu 'Main menu' @(
        'BLE Toolkit        - scan, enumerate, read/write',
        'BLE-Exploits       - authorized vulnerability PoCs',
        'BLE CTF client     - gatttool-style handle I/O',
        'View captures      - JSON evidence',
        'Quit')
    switch ($i) {
        0 { Show-ToolkitMenu }
        1 { Show-ExploitMenu }
        2 { Show-CtfMenu }
        3 { Show-Captures }
        default { $running = $false }   # Quit (index 4) or q (-1)
    }
}
try { [Console]::CursorVisible = $true } catch {}
Clear-Host
