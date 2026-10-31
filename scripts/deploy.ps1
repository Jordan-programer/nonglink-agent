# ==============================================================================
# nonglink-agent - Script de Deploy Automatizado para Windows (PowerShell)
# Uso:
#   .\scripts\deploy.ps1          # Modo local seguro (127.0.0.1)
#   .\scripts\deploy.ps1 -Demo    # Modo demonstração pública (0.0.0.0 para júri/LAN)
# ==============================================================================
[CmdletBinding()]
param(
    [switch]$Demo = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
Set-Location $RootDir

Write-Host "=== [1/5] Verificação de Ambiente e Configuração ===" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "[AVISO] Ficheiro .env não encontrado. A criar a partir de .env.example..." -ForegroundColor Yellow
        Copy-Item .env.example .env
        Write-Host "[AVISO] Configure a sua MODEL_API_KEY no ficheiro .env antes de executar em produção." -ForegroundColor Yellow
    } else {
        Write-Error "[ERRO] Ficheiro .env.example não encontrado!"
        exit 1
    }
}

Write-Host "=== [2/5] Verificação do Docker Engine e Compose ===" -ForegroundColor Cyan
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Warning "[AVISO] O executável 'docker' não foi encontrado no PATH desta máquina."
    Write-Host "Para executar com Docker em Windows, instale o Docker Desktop: https://www.docker.com/products/docker-desktop/"
    Write-Host "Se preferir executar sem Docker, consulte as instruções no README.md."
    exit 1
}

$composeFiles = @("-f", "docker-compose.yml")
if ($Demo) {
    Write-Host "[INFO] Modo Demonstração activado: portas abertas em 0.0.0.0." -ForegroundColor Green
    $composeFiles += @("-f", "docker-compose.demo.yml")
} else {
    Write-Host "[INFO] Modo Padrão: portas vinculadas a 127.0.0.1." -ForegroundColor Green
}

Write-Host "=== [3/5] Construção das Imagens (Build) ===" -ForegroundColor Cyan
& docker compose @composeFiles build

Write-Host "=== [4/5] Arranque dos Serviços ===" -ForegroundColor Cyan
& docker compose @composeFiles up -d --remove-orphans

Write-Host "=== [5/5] Verificação de Saúde (Healthcheck) ===" -ForegroundColor Cyan
$healthy = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($resp -and ($resp.estado -eq "ok" -or $resp.status -eq "ok")) {
            $healthy = $true
            break
        }
    } catch {
        # aguarda arranque do container
    }
}

if ($healthy) {
    Write-Host "✔ Backend saudável em http://127.0.0.1:8000/health" -ForegroundColor Green
    Write-Host "✔ Front-end activo em http://127.0.0.1:3000" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "  Deploy concluído com sucesso!" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
} else {
    Write-Warning "[AVISO] O backend ainda não respondeu ao healthcheck. Verifique os registos com 'docker compose logs backend'."
}
