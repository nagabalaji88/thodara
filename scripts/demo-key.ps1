# Prints a new random 32-byte key, base64-encoded, for THODARA_TWO_STEP_KEY (ADR-0015/0016).
$bytes = New-Object byte[] 32
(New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
Write-Output ([Convert]::ToBase64String($bytes))
