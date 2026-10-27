"""Vision segmentation module (app/visao.py) using Meta's sam-3.1 model."""

import base64
import json
import mimetypes
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

from openai import APIStatusError, AuthenticationError, NotFoundError, OpenAI
from PIL import Image, ImageDraw

from app.config import (
    DEFAULT_OUTPUT_BOXES_PATH,
    META_BASE_URL,
    SAMPLES_DIR,
    UPLOADS_DIR,
    VISION_SAM_MODEL,
    get_model_api_key,
)
from app.db import get_photo

DEFAULT_OUTPUT_IMAGE: str = str(DEFAULT_OUTPUT_BOXES_PATH)

CONCEPT_TRANSLATION_MAP: Dict[str, str] = {
    "tomate": "tomato",
    "tomates": "tomato",
    "mandioca": "cassava root",
    "manioc": "cassava root",
    "milho": "corn",
    "maïs": "corn",
    "mais": "corn",
    "feijao": "beans",
    "feijão": "beans",
    "haricot": "beans",
    "cafe": "coffee",
    "café": "coffee",
    "batata": "potato",
    "pomme de terre": "potato",
    "cebola": "onion",
    "oignon": "onion",
    "banana": "banana",
    "banane": "banana",
}

BOX_TOKEN_REGEX = re.compile(r"<\|box;([^|]+)\|>")


class VisionSegmentationError(RuntimeError):
    """Raised when image loading or the SAM 3.1 API call fails."""


def _normalize_prompt_concept(prompt_texto: str) -> str:
    """Translate common PT/FR agricultural terms to English noun phrases for SAM 3.1."""
    cleaned = prompt_texto.strip()
    lower = cleaned.lower()
    return CONCEPT_TRANSLATION_MAP.get(lower, cleaned)


def _upload_file_or_data_url(
    client: OpenAI, image_path: Path
) -> Tuple[Optional[str], str]:
    """Upload the image via POST /v1/files if supported, and also prepare a base64 data URL."""
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    raw_bytes = image_path.read_bytes()
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64_str}"

    file_id: Optional[str] = None
    try:
        with open(image_path, "rb") as file_handle:
            uploaded = client.files.create(file=file_handle, purpose="vision")
            file_id = getattr(uploaded, "id", None)
    except Exception:
        file_id = None

    return file_id, data_url


def _call_sam_responses(
    client: OpenAI,
    concept_text: str,
    file_id: Optional[str],
    data_url: str,
) -> str:
    """Call POST /v1/responses with model='sam-3.1' and return the raw output_text."""
    image_inputs: List[Dict[str, Any]] = []
    if file_id:
        image_inputs.append({"type": "input_image", "file_id": file_id})
    image_inputs.append({"type": "input_image", "image_url": data_url})

    last_exc: Optional[Exception] = None
    for img_block in image_inputs:
        try:
            response = client.responses.create(
                model=VISION_SAM_MODEL,
                input=[
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": concept_text},
                            img_block,
                        ],
                    }
                ],
                stream=True,
            )
            collected_chunks: List[str] = []
            for event in response:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        collected_chunks.append(str(delta))
                elif event_type == "response.completed":
                    resp_obj = getattr(event, "response", None)
                    if resp_obj and not collected_chunks:
                        out_txt = getattr(resp_obj, "output_text", "")
                        if out_txt:
                            collected_chunks.append(str(out_txt))
            return "".join(collected_chunks).strip()
        except Exception as exc:
            last_exc = exc
            continue

    if last_exc is not None:
        raise last_exc
    return ""


def _parse_kv_pairs(param_str: str) -> Dict[str, str]:
    """Parse semicolon-separated key=value pairs inside a SAM token."""
    result: Dict[str, str] = {}
    for part in param_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def _compute_box_union_coverage(
    boxes: List[Dict[str, int]], img_width: int, img_height: int
) -> float:
    """Compute the percentage of image area covered by the detected instances."""
    if not boxes or img_width <= 0 or img_height <= 0:
        return 0.0

    grid_w = min(img_width, 250)
    grid_h = min(img_height, 250)
    mask_img = Image.new("L", (grid_w, grid_h), 0)
    draw = ImageDraw.Draw(mask_img)

    sx = grid_w / float(img_width)
    sy = grid_h / float(img_height)

    for box in boxes:
        gx1 = int(round(box["x1"] * sx))
        gy1 = int(round(box["y1"] * sy))
        gx2 = max(gx1 + 1, int(round(box["x2"] * sx)))
        gy2 = max(gy1 + 1, int(round(box["y2"] * sy)))
        draw.ellipse([gx1, gy1, gx2, gy2], fill=1)

    covered_pixels = sum(mask_img.getdata())
    total_pixels = grid_w * grid_h
    pct = (covered_pixels / float(total_pixels)) * 100.0
    return round(min(100.0, max(0.0, pct)), 2)


def _parse_sam_output(
    raw_output_text: str, img_width: int, img_height: int
) -> Tuple[List[Dict[str, int]], Optional[float]]:
    """Parse SAM 3.1 output_text into pixel bounding boxes and coverage percentage."""
    if not raw_output_text.strip():
        return [], 0.0

    try:
        from meta_sam_parser import parse_image_stream  # type: ignore

        snapshot = parse_image_stream(raw_output_text)
        matches = getattr(snapshot, "matches", [])
        if matches:
            boxes: List[Dict[str, int]] = []
            for m in matches:
                b = m.box
                ref_w = float(getattr(b, "w", img_width) or img_width)
                ref_h = float(getattr(b, "h", img_height) or img_height)
                sx = img_width / ref_w
                sy = img_height / ref_h
                x1 = max(0, min(img_width, int(round(float(b.x1) * sx))))
                y1 = max(0, min(img_height, int(round(float(b.y1) * sy))))
                x2 = max(0, min(img_width, int(round(float(b.x2) * sx))))
                y2 = max(0, min(img_height, int(round(float(b.y2) * sy))))
                if x2 > x1 and y2 > y1:
                    boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
            coverage = _compute_box_union_coverage(boxes, img_width, img_height)
            return boxes, coverage
    except Exception:
        pass

    boxes = []
    for match in BOX_TOKEN_REGEX.finditer(raw_output_text):
        kv = _parse_kv_pairs(match.group(1))
        try:
            raw_x1 = float(kv.get("x1", 0))
            raw_y1 = float(kv.get("y1", 0))
            raw_x2 = float(kv.get("x2", 0))
            raw_y2 = float(kv.get("y2", 0))
            ref_w = float(kv.get("w", img_width) or img_width)
            ref_h = float(kv.get("h", img_height) or img_height)
        except ValueError:
            continue

        scale_x = img_width / ref_w if ref_w > 0 else 1.0
        scale_y = img_height / ref_h if ref_h > 0 else 1.0

        x1 = max(0, min(img_width, int(round(raw_x1 * scale_x))))
        y1 = max(0, min(img_height, int(round(raw_y1 * scale_y))))
        x2 = max(0, min(img_width, int(round(raw_x2 * scale_x))))
        y2 = max(0, min(img_height, int(round(raw_y2 * scale_y))))
        if x2 > x1 and y2 > y1:
            boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    if not boxes:
        return [], 0.0

    coverage = _compute_box_union_coverage(boxes, img_width, img_height)
    return boxes, coverage


def draw_boxes_on_image(
    source_image_path: Union[str, Path],
    boxes: List[Dict[str, int]],
    output_image_path: Union[str, Path] = DEFAULT_OUTPUT_BOXES_PATH,
) -> str:
    """Draw detected bounding boxes on the image using Pillow and save to output_image_path."""
    src_path = Path(source_image_path)
    out_path = Path(output_image_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src_path) as img:
        rgb_img = img.convert("RGB")
        draw = ImageDraw.Draw(rgb_img)
        line_width = max(2, int(min(rgb_img.size) / 180))

        for idx, box in enumerate(boxes, start=1):
            x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
            draw.rectangle([x1, y1, x2, y2], outline="#16a34a", width=line_width)
            label = f"#{idx}"
            tag_w = max(24, len(label) * 8 + 6)
            tag_h = 18
            tag_y1 = max(0, y1 - tag_h)
            draw.rectangle([x1, tag_y1, x1 + tag_w, tag_y1 + tag_h], fill="#16a34a")
            draw.text((x1 + 4, tag_y1 + 2), label, fill="#ffffff")

        rgb_img.save(out_path, format="JPEG", quality=92)

    return str(out_path)


def resolve_photo_path(
    foto_id: str, utilizador_id: Optional[str] = None
) -> Path:
    """Resolve a foto_id to an image file, enforcing utilizador_id ownership when provided."""
    cleaned = (foto_id or "").strip()
    if not cleaned:
        raise VisionSegmentationError("Foto não encontrada.")

    if utilizador_id is not None:
        photo_row = get_photo(cleaned, utilizador_id=utilizador_id)
        if photo_row is None:
            raise VisionSegmentationError("Foto não encontrada.")
        db_path = Path(str(photo_row["caminho"]))
        if db_path.exists() and db_path.is_file():
            return db_path
        raise VisionSegmentationError("Foto não encontrada.")

    photo_row = get_photo(cleaned)
    if photo_row is not None:
        db_path = Path(str(photo_row["caminho"]))
        if db_path.exists() and db_path.is_file():
            return db_path

    direct = Path(cleaned)
    if direct.exists() and direct.is_file():
        return direct

    base_name = direct.name
    for folder in (UPLOADS_DIR, SAMPLES_DIR):
        for candidate_name in (cleaned, base_name):
            candidate = folder / candidate_name
            if candidate.exists() and candidate.is_file():
                return candidate
            if folder.exists():
                for ext in (".jpg", ".jpeg", ".png", ".webp"):
                    with_ext = folder / f"{candidate_name}{ext}"
                    if with_ext.exists() and with_ext.is_file():
                        return with_ext

    raise VisionSegmentationError(
        f"Erro: Foto '{foto_id}' não encontrada em '{UPLOADS_DIR}' nem em '{SAMPLES_DIR}'."
    )


def segmentar(
    caminho_imagem: str,
    prompt_texto: str = "tomato",
    caminho_saida: Union[str, Path] = DEFAULT_OUTPUT_BOXES_PATH,
) -> Dict[str, Any]:
    """Segment objects matching prompt_texto in caminho_imagem using Meta's sam-3.1 model."""
    try:
        api_key = get_model_api_key()
    except RuntimeError as exc:
        raise VisionSegmentationError(
            "Erro: Variável MODEL_API_KEY não encontrada no ambiente (.env)."
        ) from exc

    img_path = resolve_photo_path(caminho_imagem)

    try:
        with Image.open(img_path) as img:
            img_width, img_height = img.size
    except Exception as exc:
        raise VisionSegmentationError(
            f"Erro ao abrir a imagem '{caminho_imagem}': {exc}"
        ) from exc

    client = OpenAI(base_url=META_BASE_URL, api_key=api_key)
    file_id, data_url = _upload_file_or_data_url(client, img_path)

    primary_concept = _normalize_prompt_concept(prompt_texto)
    try:
        raw_output = _call_sam_responses(
            client=client,
            concept_text=primary_concept,
            file_id=file_id,
            data_url=data_url,
        )
    except AuthenticationError as exc:
        raise VisionSegmentationError(
            "Erro 401 (Não Autorizado): A chave MODEL_API_KEY é inválida."
        ) from exc
    except NotFoundError as exc:
        raise VisionSegmentationError(
            f"Erro 404: Endpoint '{META_BASE_URL}' ou modelo '{VISION_SAM_MODEL}' não encontrado."
        ) from exc
    except APIStatusError as exc:
        raise VisionSegmentationError(
            f"Erro da API SAM 3.1 (status {exc.status_code}): {exc.message}"
        ) from exc

    boxes, coverage_pct = _parse_sam_output(raw_output, img_width, img_height)

    saved_output_path = draw_boxes_on_image(
        source_image_path=img_path,
        boxes=boxes,
        output_image_path=caminho_saida,
    )

    count = len(boxes)
    if count == 0:
        notice = (
            f"O modelo sam-3.1 não detectou nenhuma instância para '{prompt_texto}' "
            f"(conceito pesquisado: '{primary_concept}'). Nenhum valor foi inventado."
        )
    elif count < 3:
        notice = (
            f"O modelo sam-3.1 detectou poucas instâncias ({count}) para '{prompt_texto}'."
        )
    else:
        notice = (
            f"O modelo sam-3.1 detectou {count} instâncias para '{prompt_texto}' "
            f"cobrindo aproximadamente {coverage_pct}% da imagem."
        )

    return {
        "modelo": VISION_SAM_MODEL,
        "prompt_original": prompt_texto,
        "conceito_sam": primary_concept,
        "contagem": count,
        "caixas": boxes,
        "cobertura_percentagem": coverage_pct,
        "largura_imagem": img_width,
        "altura_imagem": img_height,
        "imagem_saida": saved_output_path,
        "file_id": file_id,
        "observacao": notice,
    }


segment_image = segmentar


def main() -> None:
    """CLI entry point: python -m app.visao <caminho_imagem> [prompt_texto]."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print(
            "Uso: ..\\.venv\\Scripts\\python.exe -m app.visao <caminho_imagem> [prompt_texto]",
            file=sys.stderr,
        )
        sys.exit(1)

    image_file = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else "tomato"

    try:
        result = segmentar(image_file, prompt_texto=prompt)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except VisionSegmentationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
