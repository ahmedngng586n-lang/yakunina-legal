param([string]$Config = '')
$ErrorActionPreference = 'Stop'
$landingRoot = $PSScriptRoot
$localConfig = if ($Config) { [System.IO.Path]::GetFullPath($Config) } else { Join-Path $landingRoot 'private\config.json' }
$serverPath = Join-Path $landingRoot 'server\server.py'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonCommand = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { 'python' }
if (Test-Path -LiteralPath $localConfig) {
    & $pythonCommand -X utf8 -u $serverPath --port 9137 --config $localConfig
} else {
    & $pythonCommand -X utf8 -u $serverPath --port 9137
}
