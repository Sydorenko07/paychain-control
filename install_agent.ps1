$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $PSScriptRoot).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"

Write-Host "Installing Paychain Agent in $Root" -ForegroundColor Cyan

$venvBroken = Test-Path $VenvPython
if ($venvBroken) {
    & $VenvPython --version *> $null
    $venvBroken = $LASTEXITCODE -ne 0
}
if ($venvBroken) {
    Remove-Item -LiteralPath (Join-Path $Root ".venv") -Recurse -Force
}

if (-not (Test-Path $VenvPython)) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3.12 -m venv (Join-Path $Root ".venv")
        if ($LASTEXITCODE -ne 0) { & $pyLauncher.Source -3.11 -m venv (Join-Path $Root ".venv") }
    } else {
        & python -m venv (Join-Path $Root ".venv")
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "Could not create .venv. Install Python 3.11 or 3.12 and run the installer again."
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Requirements
& $VenvPython -m playwright install chromium

$configPath = Join-Path $Root "config.json"
$configExample = Join-Path $Root "config.example.json"
if ((-not (Test-Path $configPath)) -and (Test-Path $configExample)) {
    Copy-Item -LiteralPath $configExample -Destination $configPath
}

$agentScript = Join-Path $Root "telegram_app\agent.py"
$taskName = "Paychain Control Agent"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$shortcutPath = Join-Path $startup "Paychain Control Agent.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $VenvPython
$shortcut.Arguments = ('"{0}"' -f $agentScript)
$shortcut.WorkingDirectory = $Root
$shortcut.WindowStyle = 7
$shortcut.Save()
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $VenvPython } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $VenvPython -ArgumentList ('"{0}"' -f $agentScript) -WorkingDirectory $Root -WindowStyle Hidden

Write-Host "Done. The agent is running in the background and waiting for Telegram pairing." -ForegroundColor Green
Write-Host "Open the Mini App and pair this computer. The agent will take agent-config.json from Downloads automatically." -ForegroundColor Yellow
