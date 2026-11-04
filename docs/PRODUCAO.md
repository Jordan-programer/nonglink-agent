# Guia de Operação e Produção — NongLink Agente 🌱

Este documento descreve a arquitectura, configuração, regras operacionais e procedimentos de implantação em produção do **NongLink Agente** sob o domínio **`agent.agrilink.store`**, operando de forma integrada como cliente da plataforma principal **NongLink** (`agrilink.store`).

---

## 1. Arquitectura de Produção

```
Navegador do Agricultor
       │
       ▼
agent.agrilink.store (Next.js - Porto 3200)
       │
       ▼
API do Agente (FastAPI - MODO_PLATAFORMA=api - Porto 8200)
  ├── Chamadas LLM: Meta Model API (Muse Spark 1.3, Muse Voice 1.0, SAM 3.1)
  ├── Base Local SQLite (/data/nonglink.db): Histórico de conversas, uploads e quotas
  └── Chamadas REST: API do NongLink (https://agrilink.store/api/v1 ou http://127.0.0.1:8000/api/v1)
```

### Princípios de Isolamento e Fronteiras
1. **O navegador nunca comunica directamente com a API do NongLink**: Todas as interacções passam pela API do agente. Desta forma, não há necessidade de abrir origens CORS externas na plataforma principal.
2. **A API do agente nunca acede à base de dados MySQL do NongLink**: O agente comporta-se estritamente como um cliente REST padrão.
3. **Ausência de credenciais mestras ou de serviço**: O agente **não possui** API keys globais, privilégios de administrador ou tokens delegados na plataforma NongLink. Qualquer operação é realizada estritamente com o Bearer token do agricultor autenticado.
4. **Base local leve**: O SQLite do agente armazena exclusivamente conversas, mensagens, quotas diárias e ficheiros temporários de áudio/foto associados ao identificador externo do utilizador (`utilizador_externo_id`).

---

## 2. Alocação de Portas no Servidor VPS

Para evitar conflitos com a plataforma principal já em execução, a alocação de portas na máquina host é a seguinte:

| Serviço | Projecto | Porto Host | Descrição |
|---|---|---|---|
| `nonglink-frontend` | NongLink Principal | `3000` | Interface web pública (`agrilink.store`) |
| `nonglink-admin` | NongLink Principal | `3001` | Painel administrativo (`admin.agrilink.store`) |
| `nonglink-backend` | NongLink Principal | `8000` | API FastAPI principal (`/api/v1`) |
| `nonglink-db` | NongLink Principal | `3306` | Base de dados MySQL / MariaDB |
| **`nonglink-agent-frontend`** | **NongLink Agente** | **`3200`** | Interface Next.js do Agente (`agent.agrilink.store`) |
| **`nonglink-agent-backend`** | **NongLink Agente** | **`8200`** | API FastAPI do Agente |

---

## 3. Configuração do Reverse Proxy (Caddy)

No host VPS, adicione o bloco correspondente ao subdomínio `agent.agrilink.store` no ficheiro `/etc/caddy/Caddyfile`:

```caddy
agent.agrilink.store {
    # Encaminha chamadas de API do agente para o backend do agente
    handle /api/* {
        reverse_proxy 127.0.0.1:8200
    }

    # Encaminha rotas de documentação ou uploads locais do agente
    handle /docs* {
        reverse_proxy 127.0.0.1:8200
    }
    handle /openapi.json* {
        reverse_proxy 127.0.0.1:8200
    }

    # Todo o restante tráfego serve o frontend Next.js do agente
    handle {
        reverse_proxy 127.0.0.1:3200
    }
}
```

Após editar, recarregue o Caddy:
```bash
sudo systemctl reload caddy
```

---

## 4. Variáveis de Ambiente de Produção (`.env`)

No directório `/var/www/nonglink-agent/.env`:

```env
# Meta Model API
MODEL_API_KEY=sua_chave_meta_model_api_real

# Integração com o NongLink em modo API
MODO_PLATAFORMA=api
NONGLINK_API_URL=http://127.0.0.1:8000/api/v1
NONGLINK_REGISTER_URL=https://agrilink.store/registar

# Portas e Directórios
PORT=8200
DATA_DIR=/data
NEXT_PUBLIC_API_URL=https://agent.agrilink.store/api

# Segurança e CORS
ALLOWED_CORS_ORIGINS=https://agent.agrilink.store
CORS_ORIGENS_PERMITIDAS=https://agent.agrilink.store

# Cotas e Limites
SOLO_MAX_POR_UTILIZADOR_DIA=3
QUOTA_DIARIA_REGISTADO=50
QUOTA_DIARIA_GLOBAL=600
MODO_MANUTENCAO=0
```

---

## 5. As 11 Regras Operacionais em Produção

1. **Acesso Exclusivo com Token**: Todas as chamadas para dados do agricultor requerem o token JWT de sessão fornecido pelo NongLink no login.
2. **Sem Contas Convidado em Modo API**: No modo `api`, endpoints de registo autónomo e convidados retornam HTTP 403. O agricultor é direcionado para `https://agrilink.store/registar`.
3. **Fail-Closed em Falhas de Rede**: Se a API de autenticação do NongLink estiver em baixo, o agente devolve HTTP 503 imediatamente. Nenhuma operação prossegue sem validação explícita de sessão.
4. **Protecção contra Fuga de PII e Segredos**: Tokens Bearer, senhas e chaves internas nunca são impressos em ficheiros de log (`acoes.log`), nem propagados em mensagens de erro HTTP.
5. **Confirmação Obrigatória em Duas Etapas**: Acções como `criar_anuncio`, `actualizar_anuncio`, `retirar_anuncio`, `agendar_rega` e `cancelar_rega` apenas emitem um talão de confirmação pendente. A execução é travada até o utilizador confirmar via `POST /confirmar`.
6. **Defesa contra Prompt Injection**: Dados recebidos de endpoints externos são tratados como não confiáveis e passam por validação determinística de guardas antes de qualquer apresentação ao LLM.
7. **Validação de Margem de Preço**: Preços de venda de colheitas são comparados com a cotação oficial da região obtida via `POST /market/price-suggestions` com limite de tolerância configurado.
8. **Idempotência e Reconciliação**: Submissões de rega e produtos utilizam fecho concorrente (`_ACOES_EM_CURSO`). Em caso de timeout de rede, o agente consulta `/products/mine` e `/irrigations/mine` antes de reportar qualquer falha, evitando duplicados.
9. **Limites do Estudo de Solo**: O agente não aceita upload ou desenho de polígonos no chat (os limites devem ser traçados no mapa em `agrilink.store`). Aplica cache estrito de 24 horas por parcela e cota máxima de análises de satélite GEE diárias por agricultor.
10. **Horário de Luanda (UTC+1)**: Todas as apresentações ao utilizador utilizam o fuso de Angola (`Africa/Luanda`). A conversão para UTC é tratada na comunicação com a API principal.
11. **Imutabilidade do Repositório NongLink**: O agente é um cliente autónomo e não requer qualquer alteração no código fonte ou na base de dados do projecto principal.

---

## 6. Procedimento de Teste Real em Produção

Após arrancar os contentores, execute o teste de validação do contrato utilizando o script incluído:

```bash
cd /var/www/nonglink-agent/backend
TEST_REAL_NONGLINK=1 \
NONGLINK_API_URL="http://127.0.0.1:8000/api/v1" \
TESTE_EMAIL="meta@test.com" \
TESTE_SENHA="sua_senha_aqui" \
python3 scripts/teste_real_nonglink.py
```

O script testará as 10 etapas essenciais (culturas, login, auth/me, parcelas, preços de mercado, anúncios, vendas, estudo de solo e regas) e apresentará o resumo `[OK] / [IGNORADO]` sem vazar nenhum token.

