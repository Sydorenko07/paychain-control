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

$agentScript = Join-Path $Root "telegram_app\agent.py"
$taskName = "Paychain Control Agent"
$action = New-ScheduledTaskAction -Execute $VenvPython -Argument ('"{0}"' -f $agentScript) -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description "Paychain Telegram local agent" -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

Write-Host "Done. The agent is running in the background and waiting for Telegram pairing." -ForegroundColor Green
Write-Host "Open the Mini App, pair this computer, and save agent-config.json into telegram_app." -ForegroundColor Yellow
