# NongLink Agente 🌱 (PT | FR | EN)

Assistente agrícola multimodal (**Texto, Voz e Visão**) e multilingue (**Português, Francês e Inglês**) para pequenos agricultores e cooperativas em **Angola, RDC e República do Congo**, desenvolvido para o **Meta Global AI Developer Hackathon (Categoria Startup)**.

> ⚠️ **Dados de demonstração:** Todos os preços de culturas (em Kz/kg), contagens, estimativas de peso, anúncios e agendamentos de rega são **100% fictícios para fins de demonstração**. O projecto não recolhe nem armazena dados pessoais reais.

---

## 🏗️ Arquitectura em Poucas Linhas

- **Voz (`backend/app/voz.py`):** Transcreve notas de voz do agricultor com **`muse-voice-transcribe-1.0`** (`POST /v1/asr/transcribe`), convertendo automaticamente formatos de telemóvel (`3GP/M4A/OGG/WebM/MP3`) para WAV PCM 16 kHz mono.
- **Visão (`backend/app/visao.py`):** Segmenta e conta produtos agrícolas em fotos do lote com **`sam-3.1`** (`POST /v1/files` e `POST /v1/responses`), devolvendo contagem de instâncias, caixas (`boxes`) e percentagem de cobertura da imagem.
- **Agente com Ferramentas (`backend/app/agent.py`):** Ciclo de raciocínio (máx. 5 voltas) com **`muse-spark-1.3`** (`POST /v1/responses`, `include=["reasoning.encrypted_content"]`) e 4 ferramentas: `obter_preco`, `analisar_foto`, `criar_anuncio` e `agendar_rega`.
- **Confirmação do Utilizador em Duas Etapas (`backend/app/main.py`):** Qualquer acção com efeito (`criar_anuncio` ou `agendar_rega`) pausa o ciclo em estado `"pendente"` e exige confirmação explícita do utilizador (`POST /confirmar`) antes de gravar no SQLite.
- **Histórico e Persistência SQLite (`backend/app/db.py`):** Guarda anúncios (`NL-0001`...), regas (`REGA-0001`...), preços de referência e o histórico completo de conversas (`conversas`) e mensagens (`mensagens`, incluindo `accao_json`, `estado_accao`, `resultado_id` e `anexo_json`) em `backend/data/nonglink.db`.
- **Front-end Web (`frontend/`):** Aplicação **Next.js (React + Tailwind CSS)** responsiva para telemóvel, com barra lateral de conversas, gravador de voz, visualização de fotos com caixas de segmentação num `<canvas>`, talões de confirmação e tabelas de vendas e regas.

---

## 📋 Requisitos

- **Windows PowerShell** (ou Linux/macOS compatível)
- **Python 3.9+** (com `venv`)
- **Node.js 18+ e npm** (para o front-end Next.js)
- **Chave da Meta Model API** (`MODEL_API_KEY` em `.env` na raiz)

---

## 🔐 Variáveis do `.env.example`

Copie `.env.example` para `.env` na raiz do projecto (`~\nonglink-agent\.env`):

| Variável | Obrigatória | Descrição |
| :--- | :---: | :--- |
| `MODEL_API_KEY` | **Sim** | Chave de autenticação Bearer para `https://api.meta.ai/v1` (lida exclusivamente via `backend/app/config.py`). |
| `NEXT_PUBLIC_API_URL` | Opcional | URL da API FastAPI usado pelo front-end Next.js (por omissão: `http://127.0.0.1:8000`). |

---

## 🚀 Instalação e Arranque

### 1. Configurar o `.env` e o Ambiente Python (Backend)

```powershell
cd ~\nonglink-agent
python -m venv .venv
.\.venv\Scripts\pip.exe install -r backend\requirements.txt
Copy-Item .env.example .env
# Edite o ficheiro .env e coloque a sua MODEL_API_KEY
```

### 2. Popular a Base de Dados SQLite (`backend/data/nonglink.db`)

```powershell
cd ~\nonglink-agent\backend
..\.venv\Scripts\python.exe scripts\seed.py
```

### 3. Arrancar o Backend FastAPI (`http://127.0.0.1:8000`)

```powershell
ew 
```

### 4. Instalar e Arrancar o Front-end Next.js (`http://localhost:3000`)

Num segundo terminal PowerShell:

```powershell
cd ~\nonglink-agent\frontend
npm install
npm run dev
```

Abra **[http://localhost:3000](http://localhost:3000)** no navegador.

---

## 🧪 Como Correr os Testes (`backend/tests/`)

```powershell
cd ~\nonglink-agent\backend

# 1. Teste de ligação ao modelo muse-spark-1.3 (Responses API)
..\.venv\Scripts\python.exe tests\test_meta.py

# 2. Suite de 3 testes do agente, confirmação em duas etapas e SQLite (OK / FALHOU)
..\.venv\Scripts\python.exe tests\test_agente.py

# 3. Suite de testes de Voz (muse-voice-transcribe-1.0) e Visão (sam-3.1) (OK / FALHOU)
..\.venv\Scripts\python.exe tests\test_voz_visao.py

# 4. Autenticação, sessões, palavras-passe e limite de tentativas (OK / FALHOU)
..\.venv\Scripts\python.exe tests\test_auth.py

# 5. Isolamento entre utilizadores e convidados (OK / FALHOU)
..\.venv\Scripts\python.exe tests\test_isolamento.py
```

Os testes 4 e 5 usam uma base de dados temporária `backend/nonglink_test.db`, que é apagada no fim, e não precisam da `MODEL_API_KEY`.

---

## 🔐 Autenticação e Sessões

> [!WARNING]
> **Só dados de demonstração.** Este é um protótipo de hackathon num repositório público. Use apenas dados fictícios: não introduza dados pessoais reais, palavras-passe que use noutros serviços, nem fotografias ou gravações sensíveis.

- **Autenticação obrigatória:** todos os endpoints exigem `Authorization: Bearer <token>`, excepto `POST /auth/registar`, `POST /auth/login`, `POST /auth/demo`, `/docs` e `/openapi.json`. Sem token válido a resposta é `401`.
- **Isolamento por utilizador:** conversas, mensagens, anúncios, regas, fotos e acções pendentes (`/confirmar`) pertencem a um utilizador. Um recurso de outro utilizador devolve sempre `404`. Linhas antigas sem dono ficam invisíveis.
- **Fotos:** cada foto recebe um identificador aleatório (`secrets.token_urlsafe(12)`) e só é servida ao dono em `GET /foto/{id}` / `GET /fotos/{id}`. O front-end carrega-as com `fetch` autenticado e um URL `blob:` local.
- **Sessões:** a base de dados guarda apenas o SHA-256 do token. As sessões expiram ao fim de **7 dias** (contas normais) ou **24 horas** (convidados); sessões expiradas são rejeitadas e apagadas. `POST /auth/logout` apaga a sessão.
- **Palavras-passe:** PBKDF2-HMAC-SHA256 com 600 000 iterações e sal aleatório, comparação em tempo constante (`hmac.compare_digest`), mínimo de 8 caracteres. Hashes antigos continuam a funcionar e são actualizados automaticamente ao entrar. O email é normalizado em minúsculas.
- **Tentativas de login:** qualquer falha devolve a mensagem genérica `"Email ou palavra-passe incorrectos"`. Após 5 falhas por email ou por IP em 15 minutos, as tentativas seguintes são bloqueadas (`429`). O contador é mantido em memória e reinicia com o servidor.
- **CORS:** apenas origens explícitas (`http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:8000`, `http://127.0.0.1:8000`), sem `"*"`; `allow_headers` inclui `Authorization`.
- **Front-end:** o token fica apenas em `sessionStorage` (desaparece ao fechar o separador); a palavra-passe nunca é guardada; o markdown das respostas é renderizado sem HTML bruto. Qualquer resposta `401` limpa o estado (conversas, mensagens, fotos) e mostra o ecrã de entrada.

### Convidados (botão "Continuar com conta de demonstração")

`POST /auth/demo` cria em cada chamada um **utilizador convidado novo e temporário** (email aleatório do tipo `convidado-xxxx@convidado.nonglink`, sem palavra-passe) com uma sessão de 24 horas. Cada convidado só vê os seus próprios dados; dois convidados nunca partilham conversas, anúncios, regas nem fotos. Já não existe uma conta de demonstração partilhada com entrada automática.
