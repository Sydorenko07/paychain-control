$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $PSScriptRoot).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"

Write-Host "Встановлення Paychain Agent у $Root" -ForegroundColor Cyan

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
    throw "Не вдалося створити .venv. Встанови Python 3.11 або 3.12 і запусти інсталятор ще раз."
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

Write-Host "Готово. Агент запущений у фоні та чекає підключення через Telegram." -ForegroundColor Green
Write-Host "Відкрий Mini App, натисни 'Підключити цей комп’ютер' і збережи agent-config.json у telegram_app." -ForegroundColor Yellow
