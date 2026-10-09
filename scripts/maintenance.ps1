param([ValidateSet('admin','backup','restore-test')][string]$Command)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $taskRoot
. (Join-Path $PSScriptRoot 'provider_key_check.ps1')
if ($Command -ne 'admin') { Assert-ProviderKeyFile $taskRoot }
$taskDocker=(Get-Command docker.exe -ErrorAction SilentlyContinue).Source
if (-not $taskDocker) {$taskDocker=Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'}
if (-not (Test-Path -LiteralPath $taskDocker)) {throw 'Docker CLI unavailable'}
$arguments=@('compose','--project-directory',$taskRoot,'--env-file','.env','-f','docker-compose.yml','-p','metric-control-center','--profile','web')
if ($Command -eq 'admin') {& $taskDocker @arguments exec backend python -m services.auth.bootstrap}
elseif ($Command -eq 'backup') {& $taskDocker @arguments run --rm --build backup backup}
else {
    & $taskDocker @arguments stop worker scheduler
    if ($LASTEXITCODE -ne 0) {exit $LASTEXITCODE}
    try {& $taskDocker @arguments run --rm --build backup restore-test; $result=$LASTEXITCODE}
    finally {& $taskDocker @arguments up -d worker scheduler}
    exit $result
}
exit $LASTEXITCODE
