"""Centralized configuration for the NongLink Field Agent backend.

Centralizes filesystem paths (BASE_DIR, DATA_DIR, UPLOADS_DIR, SAMPLES_DIR,
DB_PATH, LOG_FILE_PATH), Meta Model API base URL, model names, and secure
reading of MODEL_API_KEY from the root .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Directory structure
BACKEND_DIR: Path = Path(__file__).resolve().parent.parent
BASE_DIR: Path = BACKEND_DIR.parent
ENV_FILE_PATH: Path = BASE_DIR / ".env"

DATA_DIR: Path = Path(os.environ.get("DATA_DIR") or (BACKEND_DIR / "data"))
DB_PATH: Path = Path(os.environ.get("NONGLINK_DB_PATH") or (DATA_DIR / "nonglink.db"))
UPLOADS_DIR: Path = DATA_DIR / "uploads"
SAMPLES_DIR: Path = DATA_DIR / "amostras"
DEFAULT_OUTPUT_BOXES_PATH: Path = SAMPLES_DIR / "saida_caixas.jpg"
LOG_FILE_PATH: Path = DATA_DIR / "acoes.log"

FRONTEND_DIR: Path = BASE_DIR / "frontend"
ROOT_INDEX_HTML: Path = BASE_DIR / "index.html"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

# Meta Model API configuration
META_BASE_URL: str = "https://api.meta.ai/v1"
REASONING_MODEL: str = "muse-spark-1.3"
VOICE_ASR_MODEL: str = "muse-voice-transcribe-1.0"
VISION_SAM_MODEL: str = "sam-3.1"

ASR_TRANSCRIBE_URL: str = f"{META_BASE_URL}/asr/transcribe"
MAX_AGENT_TURNS: int = 5
MAX_AUDIO_FILE_BYTES: int = 25 * 1024 * 1024

# Load environment variables from the project root .env file
load_dotenv(dotenv_path=ENV_FILE_PATH)


def get_model_api_key() -> str:
    """Read and validate MODEL_API_KEY from the root .env or environment without exposing it."""
    load_dotenv(dotenv_path=ENV_FILE_PATH)
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "MODEL_API_KEY environment variable is missing. Configure it in the root .env file."
        )
    return api_key
