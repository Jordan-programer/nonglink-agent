# NongLink Agent 🌱 (PT | FR | EN)

- **PT:** Agente de campo multimodal (Texto, Voz e Visão) e multilingue (Português, Francês, Inglês) para agricultores em **Angola, RDC e Congo**, desenvolvido para o **Meta Global AI Developer Hackathon (Categoria Startup)**.
- **FR:** Agent de terrain multimodal (Texte, Voix et Vision) et multilingue (Portugais, Français, Anglais) pour les agriculteurs en **Angola, RDC et Congo**, développé pour le **Meta Global AI Developer Hackathon (Catégorie Startup)**.
- **EN:** Multimodal (Text, Voice, and Vision) and multilingual (Portuguese, French, English) field agent for farmers in **Angola, DRC, and Republic of the Congo**, built for the **Meta Global AI Developer Hackathon (Startup Category)**.

> ⚠️ **Aviso / Avertissement / Notice:** Todos os preços, contagens, estimativas de peso, anúncios e regas são **dados de demonstração 100% fictícios** (sem dados pessoais reais).

---

## 🗂️ Arquitectura do Projecto (`backend/` + `frontend/`)

```text
nonglink-agent/
├── backend/                # Backend Python (FastAPI + SQLite + Meta Model API)
│   ├── __init__.py
│   ├── api.py              # Servidor FastAPI, rotas REST e serviço do frontend
│   ├── agent.py            # Ciclo do agente (muse-spark-1.3) e ferramentas
│   ├── db.py               # Persistência SQLite (anuncios, regas, conversas, mensagens)
│   ├── seed.py             # Dados fictícios de demonstração (5 culturas em Kz/kg)
│   ├── voz.py              # Transcrição de voz (muse-voice-transcribe-1.0)
│   └── visao.py            # Segmentação de imagens (sam-3.1)
├── frontend/               # Frontend Web separado (HTML5 + CSS3 + JS puro, sem CDNs)
│   ├── index.html          # Interface principal responsiva para telemóvel
│   ├── styles.css          # Estilos mobile-first
│   └── app.js              # Integração com /conversas, /agente, /voz, /foto, /confirmar e Canvas
├── api.py, agent.py, ...   # Wrappers na raiz para compatibilidade directa com comandos CLI
├── test_meta.py            # Teste de ligação ao modelo muse-spark-1.3
├── test_agente.py          # Suite de 3 testes do agente e confirmação em duas etapas
└── test_voz_visao.py       # Suite de testes de Voz (ASR) e Visão (SAM 3.1)
```

---

## 🧠 Modelos da Meta Model API Utilizados (`https://api.meta.ai/v1`)

| Capacidade | Modelo | Endpoint |
| :--- | :--- | :--- |
| **Raciocínio & Ferramentas** | `muse-spark-1.3` | `POST /v1/responses` |
| **Transcrição de Voz (ASR)** | `muse-voice-transcribe-1.0` | `POST /v1/asr/transcribe` |
| **Segmentação Visual (Visão)** | `sam-3.1` | `POST /v1/responses` & `POST /v1/files` |

---

## 🛠️ Instalação / Installation / Setup (Windows PowerShell)

1. **Entrar na pasta do projecto:**
   ```powershell
   cd ~\nonglink-agent
   ```

2. **Criar e activar o ambiente virtual (Python 3.9+):**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Instalar as dependências (`requirements.txt`):**
   ```powershell
   .\.venv\Scripts\pip.exe install -r requirements.txt
   ```

4. **Configurar a chave da Meta Model API (`MODEL_API_KEY`):**
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

5. **Popular a base de dados SQLite (`nonglink.db`) com dados fictícios de demonstração:**
   ```powershell
   cd ~\nonglink-agent
   .\.venv\Scripts\python.exe seed.py
   ```

---

## 🌐 Correr a Aplicação Web e API FastAPI (`http://127.0.0.1:8000`)

1. **Iniciar o servidor FastAPI com Uvicorn (via `backend.api:app` ou `api:app`):**
   ```powershell
   cd ~\nonglink-agent
   .\.venv\Scripts\python.exe -m uvicorn backend.api:app --reload
   ```
   *(O comando `.\.venv\Scripts\python.exe -m uvicorn api:app --reload` também continua a funcionar).*

2. **Abrir a interface web no navegador:**
   Abra **[http://127.0.0.1:8000](http://127.0.0.1:8000)** no navegador (ou telemóvel).
   - **🗂️ Histórico de Conversas (`conversas` & `mensagens`):** crie novas conversas ou alterne entre conversas guardadas no SQLite.
   - **🎤 Botão de Microfone (`MediaRecorder`):** grava nota de voz, envia para `POST /voz`, mostra a transcrição e acciona o agente.
   - **📷 Botão Escolher / Tirar Foto:** envia foto do lote para `POST /foto` e desenha num `<canvas>` as caixas (`boxes`) detectadas pelo `sam-3.1`.
   - **✓ Confirmar / ✕ Cancelar:** qualquer proposta de anúncio (`criar_anuncio`) ou rega (`agendar_rega`) fica em estado **`pendente`** até confirmação do utilizador (`POST /confirmar`).
   - **Listas em Tempo Real:** Anúncios (`GET /anuncios`) e Regas (`GET /regas`) a partir de `nonglink.db`.

---

## 🧪 Executar os Testes (`test_meta.py`, `test_agente.py` e `test_voz_visao.py`)

```powershell
cd ~\nonglink-agent
# 1. Teste básico do modelo muse-spark-1.3
.\.venv\Scripts\python.exe test_meta.py

# 2. Suite de 3 testes do ciclo de agente e SQLite (OK / FALHOU)
.\.venv\Scripts\python.exe test_agente.py

# 3. Suite de testes de Voz (muse-voice-transcribe-1.0) e Visão (sam-3.1) (OK / FALHOU)
.\.venv\Scripts\python.exe test_voz_visao.py
```

---

## 🔌 Endpoints da API (`backend/api.py`)

| Método & Rota | Descrição |
| :--- | :--- |
| `GET /` | Serve o frontend (`frontend/index.html`) e monta `/static` (`styles.css`, `app.js`). |
| `GET /conversas` | Lista todas as conversas guardadas na tabela `conversas`. |
| `POST /conversas` | Cria uma nova conversa (`id` UUID, `titulo`, `criada_em`, `atualizada_em`). |
| `GET /conversas/{id}/mensagens` | Devolve o histórico de mensagens da conversa (`papel`, `texto`, `accao_json`, `estado_accao`, `resultado_id`, `anexo_json`). |
| `POST /agente` | Recebe `{"sessao": "...", "mensagem": "...", "foto_id": "..."}`, grava na tabela `mensagens` e corre o agente (máx. 5 voltas). |
| `POST /voz` | `multipart/form-data` (`sessao` + `audio`). Transcreve com `muse-voice-transcribe-1.0` e passa o texto ao ciclo do agente. |
| `POST /foto` | `multipart/form-data` (`sessao` + `imagem`). Guarda a foto em `uploads/` e devolve `foto_id` para `analisar_foto`. |
| `POST /confirmar` | Recebe `{"sessao": "...", "confirmar": true/false}`. Executa ou cancela a acção pendente e actualiza `estado_accao` e `resultado_id`. |
| `GET /anuncios` | Devolve JSON da tabela `anuncios` (`nonglink.db`). |
| `GET /regas` | Devolve JSON da tabela `regas` (`nonglink.db`). |
