"""Automated test suite (backend/tests/test_voz_visao.py) for Voice ASR and Vision SAM 3.1.

Runs:
1. app.voz.transcrever on data/amostras/voz_pt.wav (muse-voice-transcribe-1.0)
2. app.visao.segmentar on data/amostras/tomates.jpg (sam-3.1) and verifies data/amostras/saida_caixas.jpg
3. app.agent.analisar_foto integration test
"""

from pathlib import Path
import sys
from typing import Callable, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent import analisar_foto  # noqa: E402
from app.config import DEFAULT_OUTPUT_BOXES_PATH, SAMPLES_DIR  # noqa: E402
from app.visao import segmentar  # noqa: E402
from app.voz import transcrever  # noqa: E402

SAMPLE_AUDIO = SAMPLES_DIR / "voz_pt.wav"
SAMPLE_IMAGE = SAMPLES_DIR / "tomates.jpg"
OUTPUT_BOXES_IMAGE = DEFAULT_OUTPUT_BOXES_PATH


def test_voice_transcription() -> Tuple[bool, str]:
    """Test 1: Transcribe data/amostras/voz_pt.wav using muse-voice-transcribe-1.0."""
    if not SAMPLE_AUDIO.exists():
        return False, f"Ficheiro de amostra não encontrado: {SAMPLE_AUDIO}"

    transcript = transcrever(str(SAMPLE_AUDIO), idioma_dica="pt")
    if not transcript or len(transcript.strip()) < 3:
        return False, f"Transcrição vazia ou demasiado curta: '{transcript}'"

    return True, f"Transcrição obtida: \"{transcript}\""


def test_vision_segmentation() -> Tuple[bool, str]:
    """Test 2: Segment data/amostras/tomates.jpg using sam-3.1 and check saida_caixas.jpg."""
    if not SAMPLE_IMAGE.exists():
        return False, f"Ficheiro de amostra não encontrado: {SAMPLE_IMAGE}"

    result = segmentar(
        str(SAMPLE_IMAGE),
        prompt_texto="tomato",
        caminho_saida=str(OUTPUT_BOXES_IMAGE),
    )
    count = int(result.get("contagem", 0))
    boxes = result.get("caixas", [])
    coverage = result.get("cobertura_percentagem", 0.0)

    if count <= 0 or len(boxes) != count:
        return False, f"Segmentação devolveu contagem={count}, caixas={len(boxes)}"

    if not OUTPUT_BOXES_IMAGE.exists() or OUTPUT_BOXES_IMAGE.stat().st_size == 0:
        return False, f"Imagem com caixas não foi gerada em {OUTPUT_BOXES_IMAGE}"

    return (
        True,
        f"contagem={count} instâncias, cobertura={coverage}%, imagem gravada em {OUTPUT_BOXES_IMAGE}",
    )


def test_agent_analisar_foto_tool() -> Tuple[bool, str]:
    """Test 3: Verify the agent's analisar_foto tool returns count, coverage, boxes, and demo math."""
    res = analisar_foto(foto_id=str(SAMPLE_IMAGE), objecto="tomate")
    if res.get("status") != "executed":
        return False, f"Estado inesperado em analisar_foto: {res}"

    count = int(res.get("contagem", 0))
    if count <= 0:
        return False, "analisar_foto devolveu contagem <= 0"

    return (
        True,
        f"analisar_foto OK (contagem={count}, conta='{res.get('conta_demonstracao')}')",
    )


def main() -> None:
    """Run all Voice and Vision tests and print OK / FALHOU."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    tests: list[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
        ("Teste 1 (Voz - app.voz.transcrever com voz_pt.wav)", test_voice_transcription),
        ("Teste 2 (Visão - app.visao.segmentar com tomates.jpg)", test_vision_segmentation),
        ("Teste 3 (Agente - ferramenta analisar_foto)", test_agent_analisar_foto_tool),
    ]

    print("=== Testes de Voz (muse-voice-transcribe-1.0) e Visão (sam-3.1) ===")
    passed = 0
    for label, fn in tests:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, str(exc)

        status = "OK" if ok else "FALHOU"
        print(f"{status} - {label}: {detail}")
        if ok:
            passed += 1

    print(f"\nResumo: {passed}/{len(tests)} testes passaram.")
    if passed != len(tests):
        sys.exit(1)


if __name__ == "__main__":
    main()
