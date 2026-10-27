# Trabalho Novo no Hackathon / Nouveau Travail du Hackathon / New Hackathon Work

Todo o código, base de dados, API, interface web, testes e documentação deste repositório (`nonglink-agent`) foram criados de raiz durante o **Meta Global AI Developer Hackathon (Categoria Startup)** para a plataforma agrícola **NongLink** (Angola, RDC e Congo), com suporte multilingue (**PT, FR, EN**).

---

## 📦 Ficheiros Criados no Hackathon

### Fase 1 — Núcleo do Agente e Ligação à Meta Model API
1. **`requirements.txt`, `.env.example`, `.gitignore`**
   - Dependências (`openai`, `fastapi`, `uvicorn`, `python-dotenv`) e protecção de ficheiros locais e sensíveis (`.env`, `.venv/`, `__pycache__/`, `acoes.log`, `nonglink.db`).
2. **`test_meta.py`**
   - Script de validação da **Meta Model API** (`https://api.meta.ai/v1`, modelo `muse-spark-1.3`) via Responses API em PT/FR/EN, com tratamento dedicado de erros HTTP `401` e `404`.
3. **`agent.py`**
   - Ciclo de agente (máximo 5 voltas) com `include=["reasoning.encrypted_content"]` e preservação de `response.output` no histórico a cada volta.
   - Três ferramentas: `obter_preco(cultura)`, `criar_anuncio(cultura, quantidade_kg, preco_kz_kg)` e `agendar_rega(parcela, hora)`.
   - Confirmação obrigatória no terminal (`"s"`) antes de executar acções com efeito e registo de auditoria em `acoes.log`.
   - Prompt de sistema rigoroso: responde sempre na língua do utilizador (PT/FR/EN), nunca inventa preços/estatísticas (usa apenas `obter_preco` indicando que são valores de demonstração), pergunta quando faltam dados e exige sempre confirmação.

### Fase 2 — Persistência SQLite, Confirmação em Duas Etapas, Web UI e Testes End-to-End
4. **`db.py` (`nonglink.db`)**
   - Módulo SQLite real com as tabelas:
     - `anuncios` (`id`, `cultura`, `quantidade_kg`, `preco_kz_kg`, `criado_em`) — gera IDs sequenciais reais (`NL-0001`, `NL-0002`, ...).
     - `regas` (`id`, `parcela`, `hora`, `criado_em`) — gera IDs sequenciais reais (`REGA-0001`, `REGA-0002`, ...).
     - `precos_culturas` (`cultura`, `preco_kz_kg`, `observacao`) — tabela de referência de preços fictícios com suporte multilingue.
5. **`seed.py`**
   - Inicializa `nonglink.db` com preços fictícios de 5 culturas em Kz/kg (`tomate`, `mandioca`, `milho`, `feijão`, `café`), claramente marcados como dados fictícios de demonstração, e registos iniciais de exemplo.
6. **`api.py` (FastAPI — Confirmação em Duas Etapas)**
   - `POST /agente` (`{"sessao": "...", "mensagem": "..."}`): corre o ciclo do agente e, quando o modelo solicita `criar_anuncio` ou `agendar_rega`, pausa a execução, guarda o estado pendente em memória e devolve `{"estado": "pendente", "accao": {...}, "descricao": "..."}`.
   - `POST /confirmar` (`{"sessao": "...", "confirmar": true/false}`): executa na base de dados SQLite ou cancela a acção pendente, retoma o ciclo do modelo e devolve a resposta final.
   - `GET /anuncios` e `GET /regas`: devolvem o conteúdo JSON das tabelas SQLite.
   - `GET /`: serve a aplicação web `index.html`.
7. **`index.html`**
   - Página web única, responsiva para telemóvel e sem CDNs externos.
   - Inclui aviso visível `"Dados de demonstração"`, selector de idioma (`PT | FR | EN`), caixa de conversa, cartão de confirmação pendente com botões **Confirmar / Cancelar**, e listas em tempo real de **Anúncios** e **Regas**.
8. **`test_agente.py`**
   - Suite de testes automatizados usando a API real (`muse-spark-1.3`) para 3 cenários: (1) consulta de preço de tomate, (2) publicação de anúncio com confirmação e gravação em `nonglink.db`, e (3) cancelamento de uma acção pendente, imprimindo `OK` ou `FALHOU`.
9. **`README.md` e `NOVO_NO_HACKATHON.md`**
   - Documentação completa com instruções PowerShell.


---

### Fase 3 — Multimodalidade: Voz (`muse-voice-transcribe-1.0`) e Visão (`sam-3.1`)
10. **`voz.py`**
    - Função `transcrever(caminho_audio, idioma_dica="pt")` integrada com `POST https://api.meta.ai/v1/asr/transcribe` (`muse-voice-transcribe-1.0`, `audioEncoding="WAV"`, `mode="PUSH_TO_TALK"`, `languageBias`).
    - Conversão automática de contentores de áudio de telemóvel (`3GP/MP4/M4A/OGG/WebM/MP3`) para WAV PCM 16-bit mono a 16 kHz e tratamento claro de erros (`401`, formato inválido, limite de tamanho).
11. **`visao.py`**
    - Função `segmentar(caminho_imagem, prompt_texto)` integrada com `sam-3.1` (`POST /v1/files` e `POST /v1/responses`), descodificando a gramática de tokens `<|box;...|>` e `<|mask;...|>`.
    - Devolve contagem de instâncias (`contagem`), lista de caixas (`caixas`) e percentagem da imagem coberta (`cobertura_percentagem`), e desenha as caixas na imagem de saída `amostras\saida_caixas.jpg` com `Pillow`.
12. **Ferramenta `analisar_foto(foto_id, objecto)` em `agent.py`**
    - Chama `visao.segmentar`, devolve contagem, cobertura e caixas, e aplica as regras estritas do prompt de sistema: nunca diagnosticar doenças/qualidade a partir da foto e nunca converter unidades em quilos sem perguntar ao utilizador ou explicitar a estimativa de demonstração mostrando a conta.
13. **Novos Endpoints Multimodais em `api.py` (`POST /voz`, `POST /foto`, `GET /foto/{foto_id}`)**
    - Suporte `multipart/form-data` (`python-multipart`) para upload de notas de voz e fotografias de lotes agrícolas, integrados com o fluxo de confirmação em duas etapas (`/confirmar`).
14. **Actualização Multimodal de `index.html`**
    - Adicionado botão de gravação de voz (`MediaRecorder`, ocultado automaticamente se o navegador não suportar), botão de envio/captura de foto e `<canvas>` HTML5 que desenha a foto e as caixas (`boxes`) devolvidas pelo `sam-3.1`.
15. **`test_voz_visao.py`**
    - Suite de testes automatizados para `voz.py`, `visao.py` e `analisar_foto` com as amostras em `amostras\`, imprimindo `OK` / `FALHOU`.


---

### Fase 4 — Persistência de Conversas/Mensagens e Separação `backend/` + `frontend/`
16. **Migração Não-Destrutiva em `backend/db.py` (`conversas` e `mensagens`)**
    - Adicionada a tabela `conversas` (`id` texto UUID, `titulo`, `criada_em`, `atualizada_em`).
    - Adicionada a tabela `mensagens` (`id`, `conversa_id`, `papel` `"utilizador"`/`"agente"`, `texto`, `criado_em`, `accao_json` nulo, `estado_accao` nulo entre `"pendente"`, `"confirmada"`, `"cancelada"`, `resultado_id` nulo, `anexo_json` nulo com `{foto_id, contagem, cobertura, caixas}`).
17. **Separação e Integração `backend/` e `frontend/`**
    - **`backend/` (`__init__.py`, `db.py`, `seed.py`, `voz.py`, `visao.py`, `agent.py`, `api.py`):** Módulos do servidor organizados em pacote próprio, expondo os novos endpoints `GET /conversas`, `POST /conversas` e `GET /conversas/{conversa_id}/mensagens`, gravando automaticamente todas as mensagens, estados de acção e anexos de visão em `nonglink.db`, e servindo o frontend estático em `/` e `/static`.
    - **`frontend/` (`index.html`, `styles.css`, `app.js`):** Interface web desacoplada em HTML, CSS e JavaScript puros (sem CDNs externos), integrada com o selector de conversas SQLite, chat multimodal (texto, voz `MediaRecorder`, foto + `<canvas>` de caixas SAM 3.1), confirmação em duas etapas e listas em tempo real de anúncios e regas.
