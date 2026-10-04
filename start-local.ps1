$ErrorActionPreference = 'Stop'
$landingRoot = $PSScriptRoot
$localConfig = [System.IO.Path]::GetFullPath((Join-Path $landingRoot '..\..\work\legal-ai-secrets.json'))
$serverPath = Join-Path $landingRoot 'server\server.py'
if (Test-Path -LiteralPath $localConfig) {
    & python -u $serverPath --port 9137 --config $localConfig
} else {
    & python -u $serverPath --port 9137
}
