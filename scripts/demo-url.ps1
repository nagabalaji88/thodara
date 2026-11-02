# Prints the demo's current Cloudflare quick-tunnel address (ADR-0016). Used by start-demo.bat.
$ErrorActionPreference = "SilentlyContinue"
for ($i = 0; $i -lt 30; $i++) {
  $log = (docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml logs tunnel 2>&1) -join "`n"
  $found = [regex]::Matches($log, 'https://[a-z0-9-]+\.trycloudflare\.com')
  if ($found.Count -gt 0) { Write-Output $found[$found.Count - 1].Value; exit 0 }
  Start-Sleep -Seconds 2
}
exit 1
