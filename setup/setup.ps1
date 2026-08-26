# One-time setup for Photo Ferry. Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File .\setup\setup.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venvPy  = Join-Path $repo ".venv\Scripts\python.exe"
$venvPyw = Join-Path $repo ".venv\Scripts\pythonw.exe"
$port = 8443

Write-Host "== Photo Ferry setup ==" -ForegroundColor Cyan

# 1) venv + install
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv (Join-Path $repo ".venv")
}
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -e $repo | Out-Null

# 2) Local CA + leaf certificate (via the package's tls module -> openssl)
# "iPhonePhotoDrop" must stay identical to paths.APP_DIR_NAME -- do not rename it. The
# keys below are written by Python, at the Python path; rename only this copy and the
# Test-Path guard misses them, icacls never runs, and the private keys silently keep
# their inherited ACLs with nothing reporting an error.
$appData = Join-Path $env:LOCALAPPDATA "iPhonePhotoDrop"
New-Item -ItemType Directory -Force -Path $appData | Out-Null
Write-Host "Preparing local certificate authority + server certificate..."
& $venvPy -c "from photo_ferry import net, tls, paths; tls.setup(net.detect_lan_ip(), paths.ca_cert_path(), paths.ca_key_path(), paths.cert_path(), paths.key_path(), paths.cert_ip_marker())"
# Restrict private keys to the current user only (600-equivalent).
foreach ($k in @((Join-Path $appData "ca-key.pem"), (Join-Path $appData "key.pem"))) {
    if (Test-Path $k) { icacls $k /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null }
}

# 3) Firewall rule (scoped, Private + LocalSubnet). Needs admin: self-elevate this step.
# Must stay identical to the rule_name default in photo_ferry.net -- do not rename it.
# Existing installs already carry a rule under this exact DisplayName.
$ruleName = "iPhone Photo Drop"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Adding scoped firewall rule (a UAC prompt will appear)..."
    $fwCmd = "New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -Action Allow " +
             "-Protocol TCP -LocalPort $port -Profile Private -RemoteAddress LocalSubnet " +
             "-Program '$venvPyw'"
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile","-Command",$fwCmd
} else {
    Write-Host "Firewall rule already present."
}

# 4) Shortcut in the Pictures folder
$pictures = Join-Path $env:USERPROFILE "Pictures"
# Remove shortcuts left by earlier names, then create the current one. Their TargetPath
# is pythonw.exe, which still exists, so Windows resolves them fine and never shows a
# broken-shortcut error. What no longer exists is the module named in their Arguments,
# and pythonw has no console, so the ModuleNotFoundError goes nowhere: the user
# double-clicks and nothing at all happens, silently. That is why this loop stays.
# The delete is best-effort -- $ErrorActionPreference is Stop, and a locked or
# read-only .lnk must not abort a run that has already done the venv, the certificates
# and the UAC-prompted firewall rule.
foreach ($old in @("Receive from iPhone.lnk", "Import from iPhone.lnk")) {
    $oldLnk = Join-Path $pictures $old
    if (Test-Path $oldLnk) { Remove-Item $oldLnk -Force -ErrorAction SilentlyContinue }
}
$lnkPath  = Join-Path $pictures "Photo Ferry.lnk"
$iconPath = Join-Path $repo "assets\app.ico"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath = $venvPyw
$lnk.Arguments  = "-m photo_ferry.app"
$lnk.WorkingDirectory = $repo
if (Test-Path $iconPath) { $lnk.IconLocation = "$iconPath,0" }
else { $lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,109" }
$lnk.Description = "Import photos and videos from your iPhone (local only)"
$lnk.Save()

Write-Host "Done. Double-click 'Photo Ferry' in your Pictures folder." -ForegroundColor Green
Write-Host ""
Write-Host "Optional, one time per phone: to stop Safari's security warning, open the" -ForegroundColor Yellow
Write-Host "receiver, tap 'Trust this PC once' on the phone page, install the profile, then" -ForegroundColor Yellow
Write-Host "enable it under Settings > General > About > Certificate Trust Settings." -ForegroundColor Yellow
