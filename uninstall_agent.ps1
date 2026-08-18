$ErrorActionPreference = "Stop"
$taskName = "Paychain Control Agent"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Автозапуск Paychain Agent вимкнено. Файли проєкту не видалялися." -ForegroundColor Green
