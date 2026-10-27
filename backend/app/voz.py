"""Voice transcription module (app/voz.py) using Meta's muse-voice-transcribe-1.0."""

import array
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request
import uuid
import wave

from app.config import (
    ASR_TRANSCRIBE_URL,
    MAX_AUDIO_FILE_BYTES,
    SAMPLES_DIR,
    VOICE_ASR_MODEL,
    get_model_api_key,
)

LANGUAGE_BIAS_MAP: Dict[str, str] = {
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "portugues": "Portuguese",
    "português": "Portuguese",
    "fr": "French",
    "french": "French",
    "francais": "French",
    "français": "French",
    "en": "English",
    "english": "English",
}

SUPPORTED_EXTENSIONS = {
    ".wav",
    ".wave",
    ".m4a",
    ".3gp",
    ".mp4",
    ".ogg",
    ".opus",
    ".mp3",
    ".webm",
    ".aac",
}


class VoiceTranscriptionError(RuntimeError):
    """Raised when audio validation or the Meta ASR request fails."""


def _find_ffmpeg_executable() -> Optional[str]:
    """Locate ffmpeg in PATH or via imageio_ffmpeg."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _convert_with_ffmpeg_to_wav_16k(audio_path: Path) -> bytes:
    """Convert mobile/browser audio containers (3GP/M4A/OGG/MP3/WebM) to a clean 16 kHz mono 16-bit PCM WAV."""
    ffmpeg_exe = _find_ffmpeg_executable()
    if not ffmpeg_exe:
        raise VoiceTranscriptionError(
            f"O ficheiro '{audio_path}' está num formato comprimido (ex.: 3GP/M4A/OGG/WebM) "
            "e o endpoint /v1/asr/transcribe exige WAV PCM 16-bit mono (16 kHz ou 24 kHz).\n"
            "Instale imageio-ffmpeg (`pip install imageio-ffmpeg`) ou converta com:\n"
            f'  ffmpeg -y -i "{audio_path}" -ac 1 -ar 16000 -sample_fmt s16 saida_16k.wav'
        )

    cmd = [
        ffmpeg_exe,
        "-nostdin",
        "-y",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
        "-f",
        "s16le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    pcm_bytes = proc.stdout
    if proc.returncode != 0 or len(pcm_bytes) < 2:
        stderr_msg = proc.stderr.decode("utf-8", errors="replace").strip()[-300:]
        raise VoiceTranscriptionError(
            f"Formato de áudio não suportado ou ficheiro corrompido ('{audio_path}').\n"
            f"Detalhe da conversão: {stderr_msg}"
        )

    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[:-1]

    samples = array.array("h")
    samples.frombytes(pcm_bytes)
    if samples:
        max_amp = max(abs(x) for x in samples)
        # Normalize quiet browser microphone recordings so ASR can detect speech reliably
        if 80 < max_amp < 12000:
            gain = min(14.0, 22000.0 / float(max_amp))
            samples = array.array(
                "h",
                (max(-32768, min(32767, int(x * gain))) for x in samples),
            )

    out_buf = io.BytesIO()
    with wave.open(out_buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(samples.tobytes())
    return out_buf.getvalue()


def _normalize_wav_to_16k_mono_pcm(raw_bytes: bytes) -> bytes:
    """Ensure a WAV file is 16-bit mono integer PCM at 16 kHz or 24 kHz as required by Meta ASR."""
    try:
        with wave.open(io.BytesIO(raw_bytes), "rb") as reader:
            n_channels = reader.getnchannels()
            sampwidth = reader.getsampwidth()
            framerate = reader.getframerate()
            comptype = reader.getcomptype()
            n_frames = reader.getnframes()
            frames = reader.readframes(n_frames)
    except wave.Error as exc:
        raise VoiceTranscriptionError(
            "Formato de áudio inválido: o ficheiro não é um WAV PCM válido."
        ) from exc

    if comptype != "NONE":
        raise VoiceTranscriptionError(
            f"Formato WAV comprimido ('{comptype}') não suportado. Use PCM 16-bit não comprimido."
        )

    if n_channels == 1 and sampwidth == 2 and framerate in (16000, 24000):
        return raw_bytes

    if sampwidth != 2:
        raise VoiceTranscriptionError(
            f"Profundidade de bits WAV não suportada ({sampwidth * 8}-bit). "
            "O endpoint /v1/asr/transcribe requer PCM 16-bit (mono, 16 kHz ou 24 kHz)."
        )

    samples = array.array("h")
    samples.frombytes(frames)

    if n_channels > 1:
        mono_samples = array.array(
            "h",
            (
                int(sum(samples[i : i + n_channels]) / n_channels)
                for i in range(0, len(samples), n_channels)
            ),
        )
    else:
        mono_samples = samples

    target_rate = 16000
    if framerate != target_rate and len(mono_samples) > 1:
        duration_sec = len(mono_samples) / float(framerate)
        target_len = max(1, int(duration_sec * target_rate))
        resampled = array.array("h", [0] * target_len)
        ratio = (len(mono_samples) - 1) / float(max(1, target_len - 1))
        for idx in range(target_len):
            pos = idx * ratio
            left = int(pos)
            right = min(left + 1, len(mono_samples) - 1)
            frac = pos - left
            val = int(mono_samples[left] * (1.0 - frac) + mono_samples[right] * frac)
            resampled[idx] = max(-32768, min(32767, val))
        mono_samples = resampled

    out_buf = io.BytesIO()
    with wave.open(out_buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(target_rate)
        writer.writeframes(mono_samples.tobytes())
    return out_buf.getvalue()


def _extract_transcript_from_response(response_text: str, content_type: str) -> str:
    """Parse the transcription text from JSON, SSE, or plain-text responses."""
    stripped = response_text.strip()
    if not stripped:
        return ""

    if "application/json" in content_type or stripped.startswith("{"):
        try:
            payload: Dict[str, Any] = json.loads(stripped)
            if isinstance(payload.get("transcript"), str) and payload["transcript"].strip():
                return payload["transcript"].strip()
            if isinstance(payload.get("text"), str) and payload["text"].strip():
                return payload["text"].strip()
            turns: List[Any] = payload.get("turns", [])
            if isinstance(turns, list) and turns:
                parts: List[str] = []
                for turn in turns:
                    if isinstance(turn, dict):
                        txt = (
                            turn.get("transcript")
                            or turn.get("text")
                            or turn.get("utterance")
                            or ""
                        )
                        if txt:
                            parts.append(str(txt).strip())
                    elif isinstance(turn, str):
                        parts.append(turn.strip())
                if parts:
                    return " ".join(parts).strip()
            return ""
        except json.JSONDecodeError:
            pass

    lines: List[str] = []
    for line in stripped.splitlines():
        line_clean = line.strip()
        if not line_clean or line_clean.startswith(":"):
            continue
        if line_clean.startswith("data:"):
            data_str = line_clean[5:].strip()
            if data_str == "[DONE]":
                continue
            try:
                event_obj = json.loads(data_str)
                txt = event_obj.get("transcript") or event_obj.get("text") or ""
                if txt:
                    lines.append(str(txt).strip())
                continue
            except json.JSONDecodeError:
                lines.append(data_str)
        else:
            lines.append(line_clean)
    return " ".join(lines).strip()


def _build_multipart_body(
    request_json_bytes: bytes, filename: str, audio_bytes: bytes
) -> Tuple[bytes, str]:
    """Construct a standard multipart/form-data payload with 'request' and 'audio' parts."""
    boundary = f"----NongLinkBoundary{uuid.uuid4().hex}"
    body = io.BytesIO()

    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="request"\r\n')
    body.write(b"Content-Type: application/json\r\n\r\n")
    body.write(request_json_bytes)
    body.write(b"\r\n")

    safe_name = filename.replace('"', "")
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(
        f'Content-Disposition: form-data; name="audio"; filename="{safe_name}"\r\n'.encode(
            "utf-8"
        )
    )
    body.write(b"Content-Type: audio/wav\r\n\r\n")
    body.write(audio_bytes)
    body.write(b"\r\n")

    body.write(f"--{boundary}--\r\n".encode("utf-8"))
    content_type = f"multipart/form-data; boundary={boundary}"
    return body.getvalue(), content_type


def _resolve_audio_path(caminho_audio: str) -> Path:
    """Resolve an audio path directly or inside SAMPLES_DIR (backend/data/amostras)."""
    direct = Path(caminho_audio)
    if direct.exists() and direct.is_file():
        return direct
    in_samples = SAMPLES_DIR / direct.name
    if in_samples.exists() and in_samples.is_file():
        return in_samples
    raise VoiceTranscriptionError(
        f"Erro: Ficheiro de áudio não encontrado: '{caminho_audio}'."
    )


def transcrever(caminho_audio: str, idioma_dica: str = "pt") -> str:
    """Send an audio file to POST /v1/asr/transcribe and return the transcribed text."""
    try:
        api_key = get_model_api_key()
    except RuntimeError as exc:
        raise VoiceTranscriptionError(
            "Erro: Variável MODEL_API_KEY não encontrada no ambiente (.env)."
        ) from exc

    path_obj = _resolve_audio_path(caminho_audio)

    file_size = path_obj.stat().st_size
    if file_size == 0:
        raise VoiceTranscriptionError(
            f"Erro: O ficheiro de áudio '{caminho_audio}' está vazio."
        )
    if file_size > MAX_AUDIO_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise VoiceTranscriptionError(
            f"Erro: Ficheiro demasiado grande ({size_mb:.1f} MB). O limite máximo é 25 MB."
        )

    ext = path_obj.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise VoiceTranscriptionError(
            f"Erro: Formato de ficheiro '{ext}' não suportado."
        )

    raw_bytes = path_obj.read_bytes()
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WAVE":
        try:
            wav_bytes = _normalize_wav_to_16k_mono_pcm(raw_bytes)
        except VoiceTranscriptionError:
            wav_bytes = _convert_with_ffmpeg_to_wav_16k(path_obj)
    else:
        wav_bytes = _convert_with_ffmpeg_to_wav_16k(path_obj)

    bias_lang = LANGUAGE_BIAS_MAP.get(idioma_dica.strip().lower(), "Portuguese")
    request_config = {
        "model": VOICE_ASR_MODEL,
        "audioEncoding": "WAV",
        "mode": "PUSH_TO_TALK",
        "languageBias": [bias_lang],
        "keywords": [
            "NongLink",
            "tomate",
            "mandioca",
            "milho",
            "feijão",
            "café",
            "Kz",
            "quilos",
            "anúncio",
            "rega",
            "parcela",
        ],
    }

    request_json_bytes = json.dumps(request_config, ensure_ascii=False).encode("utf-8")
    multipart_body, multipart_content_type = _build_multipart_body(
        request_json_bytes=request_json_bytes,
        filename=path_obj.name,
        audio_bytes=wav_bytes,
    )

    req = urllib.request.Request(
        ASR_TRANSCRIBE_URL,
        data=multipart_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": multipart_content_type,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            resp_content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            raise VoiceTranscriptionError(
                "Erro 401 (Não Autorizado): A chave MODEL_API_KEY é inválida ou não tem permissão."
            ) from exc
        if exc.code == 413:
            raise VoiceTranscriptionError(
                "Erro 413: O ficheiro de áudio excede o tamanho máximo permitido pelo servidor."
            ) from exc
        if exc.code in (400, 415, 422):
            raise VoiceTranscriptionError(
                f"Erro {exc.code} (Formato/Parâmetros de áudio recusados): {err_body}"
            ) from exc
        raise VoiceTranscriptionError(
            f"Erro HTTP {exc.code} no endpoint de transcrição: {err_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise VoiceTranscriptionError(
            f"Erro de ligação ao endpoint '{ASR_TRANSCRIBE_URL}': {exc.reason}"
        ) from exc

    return _extract_transcript_from_response(resp_body, resp_content_type)


transcribe_audio = transcrever


def main() -> None:
    """CLI entry point: python -m app.voz <caminho_audio> [idioma_dica]."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print(
            "Uso: ..\\.venv\\Scripts\\python.exe -m app.voz data\\amostras\\voz_pt.wav [pt|fr|en]",
            file=sys.stderr,
        )
        sys.exit(1)

    audio_file = sys.argv[1]
    lang_hint = sys.argv[2] if len(sys.argv) > 2 else "pt"

    try:
        text = transcrever(audio_file, idioma_dica=lang_hint)
        print(text)
    except VoiceTranscriptionError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
