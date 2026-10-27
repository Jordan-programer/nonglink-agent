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
9. **Documentação:** secção de autenticação, convidados e aviso de "só dados de demonstração" no `README.md`.

> **Aviso:** este repositório é público e o projecto destina-se apenas a **dados de demonstração**.
