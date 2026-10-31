#!/usr/bin/env bash
# ==============================================================================
# nonglink-agent - Script de Deploy Automatizado (Docker Compose / VPS / Linux)
# Uso:
#   ./scripts/deploy.sh          # Modo local seguro (127.0.0.1)
#   ./scripts/deploy.sh --demo   # Modo demonstração pública (0.0.0.0 para júri/LAN)
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== [1/5] Verificação de Ambiente e Configuração ==="
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "[AVISO] Ficheiro .env não encontrado. A criar a partir de .env.example..."
        cp .env.example .env
        echo "[AVISO] Preencha a sua MODEL_API_KEY no ficheiro .env antes de executar em produção."
    else
        echo "[ERRO] Ficheiro .env.example não encontrado!" >&2
        exit 1
    fi
fi

# Alerta sobre a chave sem expor o conteúdo
if grep -q "coloque_a_sua_chave_aqui" .env 2>/dev/null; then
    echo "[AVISO] A variável MODEL_API_KEY ainda contém o valor de exemplo."
    echo "[AVISO] O assistente funcionará com respostas locais de contingência até configurar uma chave real da Meta."
fi

echo "=== [2/5] Verificação do Docker Engine e Compose ==="
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERRO] O Docker não está instalado ou não se encontra no PATH do sistema." >&2
    echo "Instale o Docker Engine seguindo: https://docs.docker.com/engine/install/" >&2
    exit 1
fi

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    echo "[ERRO] O plugin Docker Compose (v2) ou comando docker-compose não foi encontrado." >&2
    exit 1
fi

COMPOSE_FILES="-f docker-compose.yml"
if [ "${1:-}" = "--demo" ] || [ "${MODO_DEMO:-0}" = "1" ]; then
    echo "[INFO] Modo Demonstração activado: portas 8000 e 3000 abertas em 0.0.0.0."
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.demo.yml"
else
    echo "[INFO] Modo Padrão: portas 8000 e 3000 vinculadas a 127.0.0.1."
fi

echo "=== [3/5] Construção das Imagens (Build) ==="
$COMPOSE_CMD $COMPOSE_FILES build

echo "=== [4/5] Arranque dos Serviços ==="
$COMPOSE_CMD $COMPOSE_FILES up -d --remove-orphans

echo "=== [5/5] Verificação de Saúde (Healthcheck) ==="
echo "A aguardar validação do endpoint /health..."
ATTEMPTS=0
MAX_ATTEMPTS=20
HEALTHY=0

while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    if curl -s -f http://127.0.0.1:8000/health >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    ATTEMPTS=$((ATTEMPTS + 1))
    sleep 2
done

if [ $HEALTHY -eq 1 ]; then
    echo "✔ Backend saudável em http://127.0.0.1:8000/health"
    echo "✔ Front-end activo em http://127.0.0.1:3000"
    echo "============================================="
    echo "  Deploy concluído com sucesso!"
    echo "============================================="
else
    echo "[AVISO] O backend demorou mais que o esperado a responder."
    echo "Verifique os registos de diagnóstico com: $COMPOSE_CMD logs backend"
    exit 1
fi
