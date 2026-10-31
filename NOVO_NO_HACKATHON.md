# Trabalho Novo no Hackathon (`NOVO_NO_HACKATHON.md`)

Este documento distingue claramente o que existia antes do hackathon e o que foi construído de raiz durante o **Meta Global AI Developer Hackathon (Categoria Startup)** neste repositório (`nonglink-agent`).

---

## 1. O Que Já Existia Antes do Hackathon

- **Conceito e domínio NongLink:** A ideia de negócio da plataforma **NongLink** (ligar pequenos agricultores de Angola, RDC e República do Congo a mercados locais e apoiar a gestão de parcelas e rega).
- **Código neste repositório (`nonglink-agent`):** **Nada.** Todo o código-fonte deste repositório (backend FastAPI, integração com os 3 modelos da Meta Model API, base de dados SQLite, front-end Next.js e suites de testes) foi escrito do zero durante o hackathon.

---

## 2. O Que Foi Construído no Hackathon

### A. Configuração Centralizada e Segurança (`backend/app/config.py`)
- Centralização de todos os caminhos (`BASE_DIR`, `DATA_DIR`, `DB_PATH`, `UPLOADS_DIR`, `SAMPLES_DIR`, `LOG_FILE_PATH` via `pathlib`), nomes dos modelos (`muse-spark-1.3`, `muse-voice-transcribe-1.0`, `sam-3.1`), URL base `https://api.meta.ai/v1` e leitura segura de `MODEL_API_KEY` a partir do `.env` na raiz.

### B. Agente Multimodal com Ferramentas e Confirmação (`backend/app/agent.py`)
- Ciclo de agente (máximo 5 voltas) com `muse-spark-1.3` (`POST /v1/responses`), preservando `reasoning.encrypted_content` e `response.output` em cada volta.
- Quatro ferramentas:
  1. `obter_preco(cultura)` — consulta preços fictícios de demonstração em Kz/kg;
  2. `analisar_foto(foto_id, objecto)` — chama `sam-3.1`, devolve contagem, cobertura e caixas, e mostra a conta de peso médio de demonstração antes de propor um anúncio;
  3. `criar_anuncio(cultura, quantidade_kg, preco_kz_kg)` — publicação de anúncio com confirmação obrigatória;
  4. `agendar_rega(parcela, hora)` — agendamento de rega com confirmação obrigatória.
- Prompt de sistema multilingue (**PT, FR, EN**) que proíbe inventar preços/estatísticas ou diagnosticar doenças na foto.

### C. Voz ASR e Segmentação Visual SAM 3.1 (`backend/app/voz.py` e `backend/app/visao.py`)
- **`voz.py`:** Integração com `muse-voice-transcribe-1.0` (`POST /v1/asr/transcribe`, `audioEncoding="WAV"`, `mode="PUSH_TO_TALK"`, `languageBias`), incluindo conversão automática de áudio de telemóvel (`3GP/M4A/OGG/WebM/MP3`) para WAV PCM 16-bit mono a 16 kHz.
- **`visao.py`:** Integração com `sam-3.1` (`POST /v1/files` e `POST /v1/responses`), descodificação das caixas `<|box;...|>`, cálculo de percentagem de cobertura e geração da imagem anotada `saida_caixas.jpg` com `Pillow`.

### D. Base de Dados SQLite e Histórico de Conversas (`backend/app/db.py` e `backend/scripts/seed.py`)
- Persistência em `backend/data/nonglink.db` com migrações não-destrutivas:
  - `anuncios` (IDs reais `NL-0001`...), `regas` (IDs reais `REGA-0001`...) e `precos_culturas` (5 culturas em Kz/kg marcadas como dados fictícios de demonstração);
  - `conversas` (`id` UUID, `titulo`, `criada_em`, `atualizada_em`) e `mensagens` (`id`, `conversa_id`, `papel`, `texto`, `criado_em`, `accao_json`, `estado_accao`, `resultado_id`, `anexo_json`).

### E. API FastAPI com Confirmação em Duas Etapas (`backend/app/main.py`)
- Endpoints `POST /agente`, `POST /confirmar`, `POST /voz`, `POST /foto`, `GET /foto/{foto_id}` (e alias `GET /fotos/{foto_id}`), `GET /anuncios`, `GET /regas`, `GET /conversas`, `POST /conversas`, `GET /conversas/{id}`, `PATCH /conversas/{id}` e `DELETE /conversas/{id}`.

### F. Front-end Next.js (`frontend/`)
- Aplicação web em **Next.js 14 + React 18 + Tailwind CSS** com suporte multilingue (**PT, FR, EN**), barra lateral de conversas, gravador de voz (`MediaRecorder`), prova visual de foto com caixas desenhadas em `<canvas>`, talões de confirmação pendente/confirmada/cancelada e páginas dedicadas de vendas (`/vendas`), regas (`/regas`) e informações (`/sobre`).

### G. Suites de Testes Automatizados (`backend/tests/`)
- `test_meta.py`, `test_agente.py` e `test_voz_visao.py` validando a ligação real à API da Meta e a persistência SQLite.

### H. Autenticação, Isolamento por Utilizador e Endurecimento de Segurança

Trabalho feito numa sessão dedicada à segurança, em cima da autenticação por token Bearer já existente:

1. **Autenticação obrigatória sempre** (`backend/app/main.py`): uma única dependência `utilizador_atual` exige `Authorization: Bearer` em todos os endpoints, excepto `/auth/registar`, `/auth/login`, `/auth/demo`, `/docs` e `/openapi.json`. Foram removidos o cabeçalho `X-Require-Auth`, as rotas `/auth/signup` e `/auth/signin` e o dicionário de tokens em memória.
2. **Isolamento completo por utilizador** (`backend/app/db.py`, `main.py`, `agent.py`, `visao.py`): migração não destrutiva com `utilizador_id` em `anuncios` e `regas`; nova tabela `fotos` com IDs aleatórios (`secrets.token_urlsafe(12)`) e dono; `criar_anuncio`, `agendar_rega` e `analisar_foto` usam o utilizador da conversa; `/confirmar` só actua sobre acções pendentes do próprio utilizador. Qualquer recurso de outro utilizador devolve `404`.
3. **Sessões** (`sessoes_auth`): guarda apenas o SHA-256 do token, coluna `expira_em` (7 dias para contas normais, 24 horas para convidados), sessões expiradas rejeitadas e apagadas, sessões antigas em texto simples invalidadas na migração; `/auth/logout` apaga a sessão.
4. **Palavras-passe e tentativas:** PBKDF2-HMAC-SHA256 com 600 000 iterações e rehash automático dos hashes antigos ao entrar, `hmac.compare_digest`, mínimo de 8 caracteres, email em minúsculas, mensagem genérica `"Email ou palavra-passe incorrectos"` e bloqueio após 5 falhas por email e por IP em 15 minutos (em memória).
5. **Convidados em vez de conta partilhada:** `/auth/demo` cria um utilizador convidado novo e temporário (`convidado-xxxx@convidado.nonglink`, sem palavra-passe, sessão de 24 horas). Foi removida a entrada automática com a conta fixa `demo@nonglink.ao`.
6. **CORS:** origens explícitas (sem `"*"`) e `allow_headers` com `Authorization`.
7. **Testes** (`backend/tests/test_auth.py` e `backend/tests/test_isolamento.py`): base de dados temporária `nonglink_test.db` apagada no fim, com resultado OK/FALHOU por caso — 401 sem token (com e sem `X-Require-Auth`) em todos os endpoints protegidos, isolamento A/B (conversas, confirmações, anúncios, regas, fotos), sessão expirada, logout, mensagem genérica e bloqueio do 6.º intento, isolamento entre convidados e ausência de palavras-passe ou tokens nos logs.
8. **Front-end** (`frontend/src/api.js`, `context/AppContext.jsx`, `components/ProvaDeFoto.jsx`, `components/ModalAuth.jsx`): token apenas em `sessionStorage`, palavra-passe nunca guardada, markdown sem HTML bruto, qualquer `401` limpa o estado e mostra o ecrã de entrada, fotos carregadas com `fetch` autenticado e `URL.createObjectURL` (libertadas com `URL.revokeObjectURL`), com as caixas desenhadas no canvas sobre essa imagem local. `npm run build` passa.
9. **Documentação e endpoints de gestão de perfil e conta:**
   - `GET /auth/eu` devolve `criado_em`, `convidado` e `expira_em` para convidados;
   - `PATCH /auth/eu` valida nome (1-60 chars, sem chars de controlo) mantendo o email protegido;
   - `POST /auth/senha` com taxa de tentativas, PBKDF2 (600k), invalidação de todas as outras sessões e preservação da actual;
   - `POST /auth/sair-todas` com invalidação total de sessões (204);
   - `DELETE /conversas` apaga conversas, mensagens e ficheiros de fotos do utilizador mantendo anúncios e regas;
   - `DELETE /auth/eu` com confirmação rigorosa (senha para contas registadas, `APAGAR` para convidados) e remoção atómica de todos os registos e ficheiros de fotos;
   - Nova suite de testes automatizados `backend/tests/test_conta.py` (OK/FALHOU) com base temporária apagada no fim.

### I. Protecções Contra Abuso, Quotas, Endurecimento e Limpeza de Dados

1. **Quotas Diárias Contadas na Base de Dados (`backend/app/db.py`, `backend/app/main.py`):**
   - Nova tabela SQLite `chamadas_modelo` para registo e contagem de invocações (`/agente`, `/voz`, `/foto`);
   - Variáveis configuráveis com valores por omissão seguros: `QUOTA_DIARIA_CONVIDADO=15`, `QUOTA_DIARIA_REGISTADO=40` e `QUOTA_DIARIA_GLOBAL=400`;
   - Resposta com código `429` e mensagem clara em português ao atingir qualquer um dos limites.
2. **Limite de Criação de Contas por IP (`/auth/demo`):**
   - Máximo de 5 contas de convidado por endereço IP por hora (`AUTH_DEMO_MAX_POR_IP_HORA=5`), devolvendo `429` com mensagem de espera amigável.
3. **Uploads Seguros e Validação de Conteúdo:**
   - Limite de 5 MB para imagens (`UPLOAD_MAX_IMAGEM_BYTES`) e 2 MB / 60 segundos para áudio (`UPLOAD_MAX_AUDIO_BYTES`, `UPLOAD_MAX_AUDIO_SEGUNDOS`);
   - Validação dos primeiros bytes (*magic bytes*) de imagens (apenas JPEG `\xFF\xD8\xFF`, PNG `\x89PNG` e WebP `RIFF...WEBP`), rejeitando extensões forjadas com `415`;
   - Nomes de ficheiros no servidor gerados exclusivamente com tokens criptográficos aleatórios (`secrets.token_urlsafe(16)`), ignorando nomes fornecidos pelo cliente.
4. **Cabeçalhos de Segurança na Resposta das Fotos:**
   - Inclusão dos cabeçalhos `Cache-Control: private, no-store` e `X-Content-Type-Options: nosniff`.
5. **Interruptor de Emergência:**
   - Variável de ambiente `MODO_MANUTENCAO=1` intercepta chamadas aos modelos e responde `503` com mensagem explicativa para preservação imediata de créditos.
6. **Política de Retenção e Purga Automatizada (`executar_limpeza_dados_expirados`):**
   - Eliminação de contas de convidados e todos os seus recursos (mensagens, fotos, anúncios, regas e ficheiros em disco) após 24 horas (`RETENCAO_CONVIDADO_HORAS=24`);
   - Purga de conversas e fotos antigas de utilizadores registados após 30 dias (`RETENCAO_REGISTADO_DIAS=30`), mantendo vendas e regas;
   - Endpoint de manutenção `POST /admin/limpeza`.
7. **Produção e Registos Sanitizados:**
   - CORS restrito configurável via `CORS_ORIGENS_PERMITIDAS` (sem `*`);
   - Desactivação de documentação Swagger/OpenAPI via `DESATIVAR_DOCUMENTACAO_API=1`;
   - Função `log_action` sanitizada com redacção automática de chaves, palavras-passe, emails e tokens.
8. **Front-end:**
   - Banner visível no modal de entrada: *"Demonstração. Não escreva dados pessoais. Os dados de convidados são apagados após 24 horas."* (em PT, FR e EN);
   - Apresentação no ecrã de chat e no modal de mensagens informativas traduzidas para os erros `429` e `503`.
9. **Suite de Testes Automatizados (`backend/tests/test_limites.py`):**
   - 8 casos de teste com base temporária apagada no fim, validando quotas, rate limit por IP, uploads grandes, tipos inválidos, manutenção, cabeçalhos e limpeza de dados.

### J. Agente Verificável e Guardas Determinísticas (`backend/app/guardas.py`)

Desenvolvimento de um subsistema de verificações determinísticas que operam directamente dentro da execução de ferramentas e antes da devolução da resposta final, impossibilitando que o modelo contorne restrições de negócio ou invente números:

1. **Guardas Determinísticas das Ações:**
   - `validar_anuncio`: validação estrita da cultura (baseada no mapa canónico e tabela `precos_culturas`), quantidade (estritamente positiva e até ao limite `ANUNCIO_MAX_QUANTIDADE_KG`, por omissão 10 000 kg) e preço (positivo e contido no intervalo de ±50% do preço de referência via `ANUNCIO_MARGEM_PRECO_PERCENTAGEM`), verificando tanto os argumentos da ferramenta como eventuais valores solicitados pelo utilizador no texto;
   - `validar_rega`: recusa nomes de parcela vazios ou horas fora do formato `HH:MM` válido (00:00 a 23:59);
   - A recusa pela guarda devolve um motivo descritivo ao modelo para rectificação interna e **não gera acção pendente nem consome a confirmação do agricultor**.
2. **Verificador de Números Anti-Alucinação (`verificar_numeros_resposta`):**
   - Extrai valores numéricos e monetários da resposta final do modelo;
   - Valida se todos os números constam no histórico de entradas do utilizador, nas ferramentas executadas ou em cálculos aritméticos válidos derivados;
   - Em caso de discrepância, efectua até 2 voltas automáticas de correcção solicitando a remoção de dados inventados; se persistir a inconformidade, activa `gerar_resposta_segura_sem_alucinacoes` sem números fictícios.
3. **Pedir em vez de Adivinhar (`validar_prerequisitos_foto`):**
   - Bloqueia propostas automáticas de anúncios quando a contagem de frutos/produtos na foto for 0 ou se o peso médio por unidade não tiver sido fornecido pelo agricultor, forçando o modelo a pedir dados adicionais ou uma nova fotografia.
4. **Casos de Comportamento e Suite de Testes (`backend/tests/comportamento/casos.json`, `test_comportamento.py`):**
   - Definição de casos de comportamento cobrindo recusas de guardas, exigência de confirmação no talão, foto sem detecções, suporte em francês e perguntas fora do domínio;
   - Executor `test_comportamento.py` com limite de 15 chamadas ao modelo e base de dados temporária apagada no fim;
   - **Resultado medido:** 13/13 casos bem-sucedidos (**100.0% de aprovação**) com 13/15 chamadas utilizadas.

### K. Preços de Referência por Intervalo e Integração com CSV (`backend/scripts/precos_referencia.csv`)

Eliminação definitiva de preços inventados em código através de intervalos de referência estruturados e rastreáveis:

1. **Ficheiro CSV de Cotações (`backend/scripts/precos_referencia.csv`):**
   - Estrutura com colunas `cultura`, `tipo` (produtor ou retalho), `preco_min`, `preco_max`, `unidade` (kz/kg), `local`, `data`, `fonte` e `marcador`;
   - Linhas marcadas como `EXEMPLO` são estritamente ignoradas pelo script de seed a não ser que a variável `USAR_EXEMPLOS=1` esteja ativa;
   - Se o CSV não contiver registos válidos, o seed aborta imediatamente com mensagem de erro explícita em vez de recorrer a preços fictícios.
2. **Migração Não Destrutiva de `precos_culturas` (`backend/app/db.py`):**
   - Novas colunas adicionadas via `_ensure_columns`: `preco_min`, `preco_max`, `tipo`, `unidade`, `local`, `data` e `fonte`.
3. **Comportamento Transparente do Agente (`backend/app/agent.py`):**
   - A ferramenta `obter_preco` devolve o intervalo completo e os respetivos metadados de auditoria;
   - O agente informa expressamente que os dados constituem uma *"referência de demonstração, [local], [data]"*, sem fornecer um valor único como se fosse cotação fixa do dia;
   - Ao ser solicitada a publicação de um anúncio sem preço definido, sugere um valor contido no intervalo do tipo *produtor*.
4. **Guardas com Intervalo e `MARGEM_PRECO` (`backend/app/guardas.py`):**
   - Validação contra `preco_min * (1 - margem/100)` e `preco_max * (1 + margem/100)`, configurável por `MARGEM_PRECO` (por omissão 25%);
   - Recusa imediata de qualquer cultura que não possua linha cadastrada na tabela de referência.

> **Aviso:** este repositório é público e o projecto destina-se apenas a **dados de demonstração**.

### L. Camada de Integração com o Backend NongLink (Modo API)

Implementação da camada de integração com a API REST oficial do NongLink (`/api/v1`), mantendo compatibilidade total com o modo sandbox:

1. **Mapeamento Formal de Endpoints (`backend/app/integracao/mapa_endpoints.json`):**
   - Registo detalhado de todos os endpoints REST do NongLink, distinguindo os existentes dos novos criados no hackathon (módulo de regas FASE 2A).
2. **Arquitetura Desacoplada e Fábrica de Plataforma (`base.py`, `sandbox.py`, `api.py`, `fabrica.py`):**
   - `Plataforma`: Contrato comum unificado;
   - `SandboxPlataforma`: Implementação local SQLite simulada;
   - `ApiPlataforma`: Cliente httpx com timeout de 10 s e no máximo 2 repetições em 502/503/504 e falhas de rede;
   - `fabrica.py`: Escolha dinâmica via `MODO_PLATAFORMA=api` e `NONGLINK_API_URL`.
3. **Resolução Inteligente de Identificadores:**
   - Resolução de culturas insensível a acentos (`feijao` -> `Feijão`), com cache de memória de 5 minutos;
   - Resolução de parcelas a partir de `GET /farms/mine`: 1 parcela seleciona automaticamente; múltiplas parcelas solicita clarificação ao agricultor; 0 parcelas explica a necessidade de registo na plataforma sem criar nada sozinho.
4. **Autenticação Segura e Isolamento:**
   - Login no agente reencaminha para `POST /api/v1/auth/login` do NongLink e valida Bearer em `GET /auth/me` (cache de 60 s);
   - Associação de conversas ao ID do utilizador NongLink (`utilizador_externo_id`);
   - Em modo API, o registo autónomo e modo convidado são desativados com HTTP 403;
   - Falha 401 do NongLink faz o front-end regressar imediatamente ao ecrã de entrada.
5. **Preços e Guardas com Margem Configurável:**
   - `obter_preco` consome `POST /market/price-suggestions` e apresenta valor indicativo, intervalo (`min_price` a `max_price`), confiança (%) e justificação de mercado;
   - `criar_anuncio` valida o preço proposto contra o intervalo com margem `MARGEM_PRECO` (por omissão 20%);
   - Em caso de indisponibilidade da API, recusa propor o anúncio preventivamente.
6. **Prevenção de Duplicados e Reconciliação Pós-Timeout:**
   - Registo prévio da acção como "em curso" antes de chamar a API;
   - Em timeout ou erro de rede, **nunca repete às cegas**: consulta `GET /products/mine` ou `GET /irrigations/mine` para reconciliar se o recurso foi criado no servidor antes de reportar o estado.
7. **Regas com Fuso Horário de Luanda e Duração:**
   - Conversão transparente de horários em `Africa/Luanda` (WAT, UTC+1) para timestamp ISO 8601 UTC;
   - Duração da rega (`1 a 600 minutos`, por omissão 30 min via `DURACAO_REGA_PADRAO`), visível no talão de confirmação;
   - Em caso de conflito 409 (sobreposição), explica o motivo e solicita outro horário sem repetir o pedido;
   - Marcação de auditoria com `criada_via="agente"`.
8. **Upload Opcional de Imagens (`ANEXAR_FOTO=1`):**
   - Envio de foto para `POST /products/upload-image` e propagação do `image_url` no anúncio.
9. **Suite de Testes com MockTransport (`backend/tests/test_integracao_api.py`):**
   - 16 testes automatizados cobrindo token, 401, 404, 422, 5xx, timeouts, reconciliação, acentos, parcelas, conflito 409, paridade de contrato e endpoints FastAPI;
   - Teste de integração real contra o backend local NongLink (opcional, `@pytest.mark.skipif(TEST_REAL_NONGLINK != "1")`).


### K. Containerização com Docker e Preparação para Alojamento em Nuvem

1. **`backend/Dockerfile`:**
   - Imagem base `python:3.12.7-slim` (versão fixada, nunca `latest`);
   - Utilizador dedicado não-root `appuser` (UID 10001);
   - Variáveis `PYTHONUNBUFFERED=1`, `DATA_DIR=/data` e `PORT=8000`;
   - Healthcheck nativo chamando `GET http://127.0.0.1:8000/health`;
   - Respeito integral da variável `DATA_DIR` em `backend/app/config.py` para isolamento de dados no volume montado `/data`.
2. **`frontend/Dockerfile`:**
   - Multi-stage build com `node:20.18.0-alpine`;
   - Configuração de `output: "standalone"` em `next.config.mjs` para imagens ultra-leves e eficientes;
   - Utilizador dedicado não-root `nextjs` (UID 1001);
   - `ARG NEXT_PUBLIC_API_URL` com valor público e sem segredos;
   - Healthcheck nativo com `wget` na porta 3000.
3. **Orquestração `docker-compose.yml` e `docker-compose.demo.yml`:**
   - Serviços `backend` e `frontend` com volume nomeado `nonglink_data`;
   - Dependência estrita de arranque saudável (`depends_on: { backend: { condition: service_healthy } }`);
   - Publicação segura limitada a `127.0.0.1` por omissão e ficheiro de sobreposição `docker-compose.demo.yml` para publicação em `0.0.0.0` para demonstração ao júri.
4. **Isolamento de Segredos e `.dockerignore`:**
   - Ficheiros `.dockerignore` na raiz, no `backend/` e no `frontend/` impedindo a inclusão de ficheiros `.env`, segredos, bases de dados e caches;
   - Nenhum segredo gravado em `ARG` nem em `ENV` das imagens.
5. **Endpoint `/health` Público e Sem Dependências:**
   - Rota `GET /health` pública em FastAPI, devolvendo `{"estado":"ok"}` instantaneamente sem tocar na base de dados nem na API da Meta.
6. **Suporte para Variáveis de Produção:**
   - `ALLOWED_CORS_ORIGINS` (lista explícita sem `*`);
   - `ENABLE_DOCS=0` (desativação de `/docs`, `/redoc` e `/openapi.json` com retorno 404).
