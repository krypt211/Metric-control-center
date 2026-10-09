param(
    [ValidateSet('setup','start','stop','status','logs','probe','sync')][string]$Command = 'status',
    [switch]$NoPause,
    [switch]$Library
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Utf8 = New-Object Text.UTF8Encoding($false)
$Services = @('postgres','redis','migrate','backend','frontend','worker','scheduler')
$ExitCode = 0

function Write-LocalEnv {
    $path = Join-Path $Root '.env'
    $lines = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllLines($path) } else { [IO.File]::ReadAllLines((Join-Path $Root '.env.example')) }
    $settings = [ordered]@{LOCAL_READ_ONLY='true';SYNC_ENABLED='true';ACTIONS_ENABLED='false';AI_ENABLED='false';AI_AUTOPILOT_ALLOWED='false';TELEGRAM_ENABLED='false';BACKEND_PORT='8000';FRONTEND_PORT='3000';AUTH_ENABLED='true';APP_ENV='development';APP_ORIGIN='http://127.0.0.1:3000'}
    $result = New-Object 'Collections.Generic.List[string]'
    $found = @{}
    foreach ($line in $lines) {
        if ($line -match '^\s*([A-Z_]+)\s*=') {
            $name = $Matches[1]
            if ($settings.Contains($name)) {
                if (-not $found.ContainsKey($name)) { $result.Add("$name=$($settings[$name])"); $found[$name]=$true }
                continue
            }
        }
        $result.Add($line)
    }
    foreach ($name in $settings.Keys) { if (-not $found.ContainsKey($name)) { $result.Add("$name=$($settings[$name])") } }
    [IO.File]::WriteAllLines($path, $result, $Utf8)
}

function Initialize-LocalFiles {
    $dir = Join-Path $Root '.secrets'
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    foreach ($name in @('postgres_password','action_api_token','session_secret')) {
        $path = Join-Path $dir $name
        if (-not (Test-Path -LiteralPath $path)) {
            $bytes = New-Object byte[] 32
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
            [IO.File]::WriteAllText($path, [Convert]::ToBase64String($bytes), $Utf8)
        }
    }
    # Preserve the existing secret architecture. Never read the WRITE secret.
    foreach ($name in @('metricflow_read_key','metricflow_write_key','openai_api_key','telegram_bot_token')) {
        $path = Join-Path $dir $name
        if (-not (Test-Path -LiteralPath $path)) { [IO.File]::WriteAllText($path, '', $Utf8) }
    }
    Write-LocalEnv
}

function Test-ReadKey {
    $path = Join-Path $Root '.secrets/metricflow_read_key'
    return (Test-Path -LiteralPath $path) -and -not [string]::IsNullOrWhiteSpace([IO.File]::ReadAllText($path))
}

function Set-ReadKey {
    if (Test-ReadKey) { Write-Host 'MetricFlow READ key: configured'; return }
    $secure = Read-Host 'Paste MetricFlow READ API key' -AsSecureString
    $ptr = [IntPtr]::Zero
    try {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim()
        if ($key -cnotmatch '^(?:mfk_|mf_live_)[\x21-\x7e]+$' -or $key.Contains('*')) { throw 'Invalid key format. Use the complete MetricFlow READ key (mfk_ or mf_live_), without spaces or masking characters. Nothing was saved.' }
        [IO.File]::WriteAllText((Join-Path $Root '.secrets/metricflow_read_key'), $key, $Utf8)
        Write-Host 'MetricFlow READ key: configured'
    } finally {
        $key = $null
        if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        $secure.Dispose()
    }
}

function Require-Docker {
    $script:Docker = (Get-Command docker.exe -ErrorAction SilentlyContinue).Source
    if (-not $script:Docker) {
        $programFiles = if ($env:ProgramFiles) { $env:ProgramFiles } else { 'C:\Program Files' }
        $candidate = Join-Path $programFiles 'Docker/Docker/resources/bin/docker.exe'
        if (Test-Path -LiteralPath $candidate) { $script:Docker = $candidate }
    }
    if (-not $script:Docker) { throw 'Docker Desktop is not installed. Install Docker Desktop with Linux containers, then open it and run start.bat again.' }
    & $script:Docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running, or Linux containers are unavailable. Open Docker Desktop and wait until the engine is ready.' }
    & $script:Docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is unavailable. Update Docker Desktop.' }
}

function Set-SafeEnvironment {
    $env:LOCAL_READ_ONLY='true'; $env:SYNC_ENABLED='true'; $env:ACTIONS_ENABLED='false'
    $env:AI_ENABLED='false'; $env:AI_AUTOPILOT_ALLOWED='false'; $env:TELEGRAM_ENABLED='false'
    $env:BACKEND_PORT='8000'; $env:FRONTEND_PORT='3000'; $env:COMPOSE_PROFILES=''
}

function Compose {
    param([string[]]$Arguments, [switch]$Capture, [switch]$Application)
    $base = @('compose','--project-directory',$Root,'--env-file',(Join-Path $Root '.env'),'-f',(Join-Path $Root 'docker-compose.yml'),'-p','metric-control-center','--profile','web')
    if ($Application) {
        $output = @(& $script:Docker @base @Arguments)
        $applicationCode = $LASTEXITCODE
        foreach ($line in $output) { Write-Host $line }
        $started = ($output -join "
") -match '(?m)^MCC_APPLICATION_STARTED\s*$'
        if ($started -and $applicationCode -in @(0,20,21,22,23)) {
            Write-Host 'Docker: OK'
            if ($applicationCode -ne 0) {
                $ready = Read-Http 'http://127.0.0.1:8000/health/ready'
                Write-Host ('LOCAL APPLICATION: ' + $(if ($ready -and $ready.status -eq 'ready') {'PASS'} else {'NOT VERIFIED'}))
                switch ($applicationCode) {
                    20 { Write-Host 'READ Authentication / API: FAILED'; Write-Host 'Import: NOT STARTED' }
                    21 { Write-Host 'Schema: FAILED'; Write-Host 'Import: NOT PUBLISHED' }
                    22 { Write-Host 'Import: FAILED' }
                    23 { Write-Host 'READ quota: BLOCKED'; Write-Host 'Import: NOT PUBLISHED' }
                }
            }
            return $applicationCode
        }
        throw 'Docker execution failed before a recognized application result. Check Docker Desktop and logs.bat.'
    }
    if ($Capture) { $output = & $script:Docker @base @Arguments; if ($LASTEXITCODE -ne 0) { throw 'Docker command failed. Check logs.bat and Docker Desktop.' }; return $output }
    & $script:Docker @base @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed. Check the message above or logs.bat. No success status was assumed.' }
}

function Get-ContainerInfo([string]$Service) {
    $id = @(Compose -Arguments @('ps','--all','--quiet',$Service) -Capture) | Select-Object -First 1
    if (-not $id) { return $null }
    $raw = & $script:Docker inspect --format '{{json .State}}' $id
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($raw | ConvertFrom-Json)
}

function Read-Http([string]$Url) {
    try { return Invoke-RestMethod -Uri $Url -TimeoutSec 5 -UseBasicParsing } catch { return $null }
}

function Wait-Http([string]$Url, [int]$Seconds=120) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $result = Read-Http $Url
        if ($null -ne $result) { return $result }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Application did not become ready at $Url. Run logs.bat. Check whether ports 3000/8000 are occupied."
}

function Show-Status {
    $ok = $true
    Write-Host '========================================'
    Write-Host 'Metric Control Center - LOCAL READ ONLY'
    Write-Host '========================================'
    foreach ($name in $Services) {
        $state = Get-ContainerInfo $name
        $value = 'STOPPED'
        if ($state) {
            if ($name -eq 'migrate') { if ($state.Status -eq 'exited' -and $state.ExitCode -eq 0) { $value='OK' } else { $value='FAILED/PENDING' } }
            elseif ($state.Status -eq 'running') {
                $value = if ($state.Health) { if ($state.Health.Status -eq 'healthy') { 'OK' } else { $state.Health.Status.ToUpper() } } else { 'RUNNING' }
            } else { $value=$state.Status.ToUpper() }
        }
        if ($value -notin @('OK','RUNNING')) { $ok=$false }
        Write-Host ('{0,-18} {1}' -f $name,$value)
    }
    $live = Read-Http 'http://127.0.0.1:8000/health/live'
    $ready = Read-Http 'http://127.0.0.1:8000/health/ready'
    $front = Read-Http 'http://127.0.0.1:3000/api/auth/csrf'
    if (-not $live -or -not $ready -or -not $front) { $ok=$false }
    Write-Host ('Backend readiness  ' + $(if ($ready -and $ready.status -eq 'ready') {'OK'} else {'NOT READY'}))
    Write-Host ('Frontend HTTP      ' + $(if ($front) {'OK'} else {'UNAVAILABLE'}))
    $worker = Get-ContainerInfo 'worker'
    if ($worker -and $worker.Status -eq 'running') {
        try {
            $pong = (Compose -Arguments @('exec','-T','worker','celery','-A','workers.ingestion:app','inspect','ping','--timeout','5','--json') -Capture) -join "\n"
            $answered = $pong -match '"ok"\s*:\s*"pong"'
        } catch { $answered=$false }
        Write-Host ('Worker response    ' + $(if ($answered) {'OK'} else {'NO RESPONSE'}))
        if (-not $answered) { $ok=$false }
    }
    $sync = Read-Http 'http://127.0.0.1:8000/api/system/status'
    if ($sync) {
        Write-Host ('Sync enabled       ' + $sync.sync_enabled)
        Write-Host ('Sync schema        ' + $(if ($sync.schema_configured) {'CONFIGURED'} else {'WAITING - run sync_now.bat after the READ probe'}))
        if ($sync.last_sync) {
            Write-Host ('Last sync          ' + $sync.last_sync.status + ' / ' + $sync.last_sync.started_at)
            Write-Host ('Sync rows          ' + $sync.last_sync.rows)
            if ($sync.last_sync.error_code) { Write-Host ('Sync error         ' + $sync.last_sync.error_code) }
        } else { Write-Host 'Last sync          NOT RUN YET' }
        if ($sync.actions_enabled -or $sync.mode -ne 'LOCAL READ ONLY' -or -not $sync.sync_enabled) { $ok=$false; Write-Host 'Mode check         FAILED - run start.bat to recreate safe services' }
    }
    Write-Host ('MetricFlow Key     ' + $(if (Test-ReadKey) {'CONFIGURED'} else {'MISSING - run setup.bat'}))
    Write-Host ''
    Write-Host 'Dashboard: http://127.0.0.1:3000'
    Write-Host 'Backend:   http://127.0.0.1:8000'
    Write-Host 'Health:    http://127.0.0.1:8000/health/ready'
    Write-Host 'Actions:   DISABLED (required in this mode)'
    Write-Host 'Mode:      READ ONLY'
    Write-Host '========================================'
    return $ok
}

if ($Library) { return }
try {
    Set-Location -LiteralPath $Root
    Set-SafeEnvironment
    if ($Command -eq 'setup') {
        Initialize-LocalFiles
        Set-ReadKey
        Write-Host 'Setup complete. Open Docker Desktop, then run start.bat.'
        Write-Host 'After startup: probe_read.bat, then sync_now.bat.'
    } else {
        if (-not (Test-Path -LiteralPath (Join-Path $Root '.env'))) { throw 'Local configuration is missing. Run setup.bat first.' }
        Require-Docker
        switch ($Command) {
            'start' {
                . (Join-Path $PSScriptRoot 'provider_key_check.ps1')
                Assert-ProviderKeyFile $Root
                if (-not (Test-ReadKey)) { throw 'MetricFlow READ key is missing. Run setup.bat and paste your READ key.' }
                Write-LocalEnv
                # Stop any old optional processes before starting the read-only stack.
                Compose -Arguments @('--profile','actions','--profile','ai','--profile','telegram','stop','action-worker','ai-worker','telegram-bot')
                Compose -Arguments @('up','-d','--wait','--wait-timeout','120','postgres','redis')
                Compose -Arguments @('up','--build','--no-deps','--exit-code-from','migrate','migrate')
                Compose -Arguments @('up','-d','--build','--wait','--wait-timeout','180','backend','worker','scheduler','frontend')
                Wait-Http 'http://127.0.0.1:8000/health/live' | Out-Null
                Wait-Http 'http://127.0.0.1:8000/health/ready' | Out-Null
                Wait-Http 'http://127.0.0.1:3000/api/auth/csrf' | Out-Null
                if (-not (Show-Status)) { throw 'Some startup checks failed. Run status.bat and logs.bat.' }
                Write-Host 'LOCAL APPLICATION: PASS'
                Write-Host 'First connection: run probe_read.bat, then sync_now.bat.'
            }
            'stop' {
                Compose -Arguments @('--profile','actions','--profile','ai','--profile','telegram','down','--timeout','30')
                Write-Host 'Application stopped. Database and Redis volumes have been kept.'
            }
            'status' { if (-not (Show-Status)) { $ExitCode=1 } }
            'logs' {
                Write-Host 'Press Ctrl+C to leave logs. Containers will keep running.'
                Compose -Arguments @('logs','--tail','100','--follow','backend','worker','scheduler','frontend','migrate','postgres','redis')
            }
            'probe' {
                if (-not (Test-ReadKey)) { throw 'MetricFlow READ key is missing. Run setup.bat.' }
                $ExitCode = Compose -Application -Arguments @('exec','-T','worker','python','-m','services.metricflow.probe','--summary')
            }
            'sync' {
                if (-not (Test-ReadKey)) { throw 'MetricFlow READ key is missing. Run setup.bat.' }
                $ExitCode = Compose -Application -Arguments @('run','--rm','-T','--no-deps','--volume',($Root.Replace('\','/') + '/config:/config'),'worker','python','-m','services.metricflow.local','sync')
            }
        }
    }
} catch {
    $ExitCode=1
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'LOCAL APPLICATION: FAIL / NOT VERIFIED'
}
if (-not $NoPause -and ($Command -ne 'logs' -or $ExitCode -ne 0)) { [void](Read-Host 'Press Enter to close') }
exit $ExitCode
