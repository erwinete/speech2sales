$output = docker compose build asterisk --progress=plain 2>&1 | Out-String
$lines = $output -split "`n"
$err = $lines | Where-Object { $_ -match '#\d+ \d+\.' -or $_ -match 'E: ' -or $_ -match 'Err:' -or $_ -match 'Unable to' -or $_ -match 'ERROR' } | Select-Object -Last 25
$err | ForEach-Object { Write-Output $_ }
