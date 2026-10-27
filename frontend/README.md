# NongLink Agente — Front-end

Interface web (Next.js, React e Tailwind CSS) do assistente **NongLink Agente** para agricultores de Angola, RDC e Congo.

## Instalação

```bash
npm install
```

## Variável do URL da API

Por omissão, a aplicação liga-se a `http://127.0.0.1:8000`. Para configurar outro endereço da API FastAPI, defina `NEXT_PUBLIC_API_URL` (ou `VITE_API_URL`):

```bash
# PowerShell
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"

# Bash / .env.local
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

## Arranque

Modo de desenvolvimento:

```bash
npm run dev
```

Compilação e arranque em produção:

```bash
npm run build
npm run start
```
