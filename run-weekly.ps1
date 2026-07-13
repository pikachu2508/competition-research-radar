$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
& python "$Root\weekly_digest.py"
exit $LASTEXITCODE
