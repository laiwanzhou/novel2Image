param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 5173,
    [string]$PostgresContainer = "novel-vis-pgvector",
    [string]$ApiBaseUrl = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogsDir = Join-Path $Root "logs"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Wait-ForHttp {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "Timed out waiting for $Url"
}

function Wait-ForTcp {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
        if ($result.TcpTestSucceeded) {
            return
        }
        Start-Sleep -Seconds 3
    }

    throw "Timed out waiting for ${HostName}:${Port}"
}

function Stop-PortProcess {
    param([int]$Port)

    Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
            }
            catch {
                Write-Warning "Could not stop process $($_.OwningProcess) on port $Port"
            }
        }
}

if (-not $ApiBaseUrl) {
    $ApiBaseUrl = "http://127.0.0.1:$BackendPort"
}

Write-Host "Project root: $Root"

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    }
    else {
        throw "Docker is not running, and Docker Desktop was not found at $dockerDesktop"
    }

    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 5
        docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            break
        }
    } while ((Get-Date) -lt $deadline)

    if ($LASTEXITCODE -ne 0) {
        throw "Docker did not become ready within 3 minutes."
    }
}

$containerExists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $PostgresContainer }
if (-not $containerExists) {
    Write-Host "Creating Postgres pgvector container: $PostgresContainer"
    docker run --name $PostgresContainer `
        -e POSTGRES_PASSWORD=postgres `
        -e POSTGRES_DB=novel_visualization `
        -p 5432:5432 `
        -d registry.cn-hangzhou.aliyuncs.com/fastgpt/pgvector:0.8.0-pg15 | Out-Host
}
else {
    $running = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $PostgresContainer }
    if (-not $running) {
        Write-Host "Starting Postgres container: $PostgresContainer"
        docker start $PostgresContainer | Out-Host
    }
}

Wait-ForTcp -HostName "127.0.0.1" -Port 5432

Write-Host "Running Alembic migrations..."
Push-Location $BackendDir
try {
    .\.venv\Scripts\python -m alembic upgrade head
}
finally {
    Pop-Location
}

Stop-PortProcess -Port $BackendPort
Stop-PortProcess -Port $FrontendPort

$backendOut = Join-Path $LogsDir "backend-$BackendPort.out.log"
$backendErr = Join-Path $LogsDir "backend-$BackendPort.err.log"
$frontendOut = Join-Path $LogsDir "frontend-$FrontendPort.out.log"
$frontendErr = Join-Path $LogsDir "frontend-$FrontendPort.err.log"

Write-Host "Starting backend on $ApiBaseUrl"
$backendCmd = "cd /d `"$BackendDir`" && .\.venv\Scripts\python -m uvicorn app.api.main:app --host 127.0.0.1 --port $BackendPort"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $backendCmd -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
Wait-ForHttp -Url "$ApiBaseUrl/health"

Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort"
$frontendCmd = "cd /d `"$FrontendDir`" && set VITE_API_BASE_URL=$ApiBaseUrl&& npm run dev -- --host 127.0.0.1 --port $FrontendPort"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $frontendCmd -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr
Wait-ForHttp -Url "http://127.0.0.1:$FrontendPort/"

Write-Host ""
Write-Host "Services are ready:"
Write-Host "  Postgres:  localhost:5432 ($PostgresContainer)"
Write-Host "  Backend:   $ApiBaseUrl"
Write-Host "  Frontend:  http://127.0.0.1:$FrontendPort"
Write-Host ""
Write-Host "Logs:"
Write-Host "  $backendOut"
Write-Host "  $backendErr"
Write-Host "  $frontendOut"
Write-Host "  $frontendErr"
