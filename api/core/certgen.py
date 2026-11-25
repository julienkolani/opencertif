import io
import json
import re
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import qrcode
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .config import Settings


def load_template_positions(positions_file: str) -> dict[str, Any]:
    with open(positions_file, encoding="utf-8") as f:
        return json.load(f)


def save_template_positions(positions_file: str, data: dict[str, Any]) -> None:
    path = Path(positions_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_available_types(positions_file: str) -> list[str]:
    return list(load_template_positions(positions_file).keys())


def calculate_font_size(
    text: str,
    font_name: str,
    max_size: int,
    min_size: int,
    max_width: float,
) -> int:
    size = max_size
    while size > min_size:
        if stringWidth(text, font_name, size) <= max_width:
            return size
        size -= 1
    return min_size


def generate_qr_code(url: str, size: int) -> bytes:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    image = image.resize((size, size))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _build_overlay(
    page_width: float,
    page_height: float,
    display_name: str,
    font_name: str,
    font_size: int,
    name_position: dict[str, float],
    qr_bytes: bytes,
    qr_position: dict[str, float],
    qr_size: int,
) -> io.BytesIO:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    c.setFont(font_name, font_size)
    c.drawCentredString(name_position["x"], name_position["y"], display_name)

    qr_image = ImageReader(io.BytesIO(qr_bytes))
    c.drawImage(
        qr_image,
        qr_position["x"],
        qr_position["y"],
        width=qr_size,
        height=qr_size,
        mask="auto",
    )

    c.save()
    buffer.seek(0)
    return buffer


def _get_type_config(positions_file: str, cert_type: str) -> dict[str, Any]:
    positions = load_template_positions(positions_file)
    if cert_type not in positions:
        raise ValueError(f"Unknown certificate type: {cert_type}")
    return positions[cert_type]


def _build_writer_with_overlay(
    template_path: Path,
    config: dict[str, Any],
    display_name: str,
    font_size: int,
    qr_bytes: bytes,
) -> tuple[PdfWriter, int]:
    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    name_page_index = config.get("name_page", 1) - 1
    target_page = writer.pages[name_page_index]
    page_width = float(target_page.mediabox.width)
    page_height = float(target_page.mediabox.height)

    overlay_buffer = _build_overlay(
        page_width,
        page_height,
        display_name,
        config["name_font"],
        font_size,
        config["name_position"],
        qr_bytes,
        config["qr_position"],
        config["qr_size"],
    )
    overlay_reader = PdfReader(overlay_buffer)
    target_page.merge_page(overlay_reader.pages[0])
    return writer, name_page_index


def _safe_filename_part(text: str) -> str:
    """Filename-safe version of a participant name (the PDF shows the real
    one). Keeps letters, accented ones included, digits, '-' and '_'; any
    other run of characters ("/", "..", spaces, quotes) becomes "_", so a
    name like "Jean/Paul" can neither fail the write nor leave CERTIFS_DIR."""
    cleaned = re.sub(r"[^\w-]+", "_", text).strip("_")
    return cleaned[:100] or "certificat"


def generate_certificate(
    name: str,
    first_name: str,
    event_name: str,
    event_date: str,
    cert_type: str,
    cert_id: str,
    settings: Settings,
) -> str:
    config = _get_type_config(settings.POSITIONS_FILE, cert_type)

    display_name = f"{first_name} {name.upper()}"
    font_size = calculate_font_size(
        display_name,
        config["name_font"],
        config["name_max_size"],
        config["name_min_size"],
        config["name_max_width"],
    )

    qr_url = f"{settings.BASE_URL}/verifier?code={cert_id}"
    qr_bytes = generate_qr_code(qr_url, config["qr_size"])

    template_path = Path(settings.TEMPLATES_DIR) / config["template_file"]
    writer, _ = _build_writer_with_overlay(
        template_path, config, display_name, font_size, qr_bytes
    )

    event_year = event_date.split("-")[0]
    safe_name = _safe_filename_part(f"{name.upper()}_{first_name}")
    output_dir = Path(settings.CERTIFS_DIR) / event_year / cert_type
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{cert_id}_{safe_name}.pdf"

    with open(output_path, "wb") as f:
        writer.write(f)

    return str(output_path)


def _merge_config(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def render_preview(
    cert_type: str,
    test_name: str,
    settings: Settings,
    overrides: dict[str, Any] | None = None,
) -> bytes:
    """Renders a preview PNG for `cert_type`.

    `overrides` lets callers preview not-yet-saved position/size values
    (used by the positions editor's live preview) without writing them to
    template_positions.json; only save_template_positions() persists.
    """
    config = _get_type_config(settings.POSITIONS_FILE, cert_type)
    if overrides:
        config = _merge_config(config, overrides)

    font_size = calculate_font_size(
        test_name,
        config["name_font"],
        config["name_max_size"],
        config["name_min_size"],
        config["name_max_width"],
    )

    qr_url = f"{settings.BASE_URL}/verifier?code=PREVIEW"
    qr_bytes = generate_qr_code(qr_url, config["qr_size"])

    template_path = Path(settings.TEMPLATES_DIR) / config["template_file"]
    writer, name_page_index = _build_writer_with_overlay(
        template_path, config, test_name, font_size, qr_bytes
    )

    single_page_writer = PdfWriter()
    single_page_writer.add_page(writer.pages[name_page_index])
    pdf_buffer = io.BytesIO()
    single_page_writer.write(pdf_buffer)
    pdf_buffer.seek(0)

    pdf_doc = pdfium.PdfDocument(pdf_buffer)
    page = pdf_doc[0]
    bitmap = page.render(scale=2)
    pil_image = bitmap.to_pil()

    image_buffer = io.BytesIO()
    pil_image.save(image_buffer, format="PNG")
    return image_buffer.getvalue()
