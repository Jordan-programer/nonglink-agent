"""Validation test script (backend/tests/test_meta.py) for the Meta Model API (muse-spark-1.3).

Verifies connectivity to https://api.meta.ai/v1 via the OpenAI Python SDK
Responses API using MODEL_API_KEY from the root .env file.
"""

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from openai import APIStatusError, AuthenticationError, NotFoundError, OpenAI  # noqa: E402

from app.config import META_BASE_URL, REASONING_MODEL, get_model_api_key  # noqa: E402

DEFAULT_PROMPTS = {
    "pt": (
        "Responde em 2 frases curtas: como o agente NongLink pode ajudar um "
        "agricultor em Angola a vender tomate e planear a rega?"
    ),
    "fr": (
        "Réponds en 2 phrases courtes : comment l'agent NongLink peut-il aider "
        "un agriculteur en RDC ou au Congo à vendre du manioc et planifier l'irrigation ?"
    ),
    "en": (
        "Reply in 2 short sentences: how can the NongLink agent help a farmer "
        "in Angola or DRC sell maize and schedule irrigation?"
    ),
}


def run_meta_test(prompt: str) -> str:
    """Send a test prompt to Meta's muse-spark-1.3 model via the Responses API."""
    client = OpenAI(
        base_url=META_BASE_URL,
        api_key=get_model_api_key(),
    )
    response = client.responses.create(
        model=REASONING_MODEL,
        input=prompt,
    )
    return response.output_text


def main() -> None:
    """CLI entry point for testing the Meta Model API."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    lang = "pt"
    custom_prompt = None
    for arg in sys.argv[1:]:
        if arg.lower() in ("--fr", "fr"):
            lang = "fr"
        elif arg.lower() in ("--en", "en"):
            lang = "en"
        elif arg.lower() in ("--pt", "pt"):
            lang = "pt"
        else:
            custom_prompt = arg

    prompt = custom_prompt or DEFAULT_PROMPTS[lang]

    try:
        output_text = run_meta_test(prompt)
        print(f"OK - Modelo {REASONING_MODEL} respondeu com sucesso:\n{output_text}")
    except AuthenticationError:
        print(
            "FALHOU - Erro 401 (Não Autorizado): A chave MODEL_API_KEY é inválida.",
            file=sys.stderr,
        )
        sys.exit(1)
    except NotFoundError:
        print(
            f"FALHOU - Erro 404: Endpoint '{META_BASE_URL}' ou modelo '{REASONING_MODEL}' não encontrado.",
            file=sys.stderr,
        )
        sys.exit(1)
    except APIStatusError as exc:
        print(
            f"FALHOU - Erro da API (status {exc.status_code}): {exc.message}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"FALHOU - Erro: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
