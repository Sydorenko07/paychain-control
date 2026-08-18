$ErrorActionPreference = "Stop"
$taskName = "Paychain Control Agent"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$shortcutPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Paychain Control Agent.lnk"
Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
Write-Host "Paychain Agent startup disabled. Project files were not removed." -ForegroundColor Green
