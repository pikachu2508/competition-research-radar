$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
& python "$Root\radar.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& python "$Root\daily_digest.py"
exit $LASTEXITCODE
