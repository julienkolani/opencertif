import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from core import certgen
from core import config as config_module

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _make_blank_pdf(path: Path, pages: int = 1) -> None:
    """Mock A4-landscape template PDF, used since no real template is available."""
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    for _ in range(pages):
        c.showPage()
    c.save()


@pytest.fixture
def positions_data():
    return {
        "participation": {
            "template_file": "Certificat_participation.pdf",
            "name_position": {"x": 421, "y": 300},
            "name_font": "Helvetica-Bold",
            "name_max_size": 36,
            "name_min_size": 18,
            "name_max_width": 500,
            "qr_position": {"x": 50, "y": 50},
            "qr_size": 80,
            "pages": 1,
            "name_page": 1,
        },
        "organisation_2020": {
            "template_file": "Certificat_organisation_2020.pdf",
            "name_position": {"x": 460, "y": 340},
            "name_font": "Helvetica-Bold",
            "name_max_size": 36,
            "name_min_size": 18,
            "name_max_width": 500,
            "qr_position": {"x": 50, "y": 50},
            "qr_size": 80,
            "pages": 2,
            "name_page": 1,
        },
    }


@pytest.fixture
def settings(tmp_path, monkeypatch, positions_data):
    templates_dir = tmp_path / "templates"
    certifs_dir = tmp_path / "certifs"
    templates_dir.mkdir()
    certifs_dir.mkdir()

    _make_blank_pdf(templates_dir / "Certificat_participation.pdf", pages=1)
    _make_blank_pdf(templates_dir / "Certificat_organisation_2020.pdf", pages=2)

    positions_file = tmp_path / "template_positions.json"
    positions_file.write_text(json.dumps(positions_data), encoding="utf-8")

    monkeypatch.setenv("BASE_URL", "https://certifs.example.com")
    monkeypatch.setenv("TEMPLATES_DIR", str(templates_dir))
    monkeypatch.setenv("CERTIFS_DIR", str(certifs_dir))
    monkeypatch.setenv("POSITIONS_FILE", str(positions_file))
    config_module.get_settings.cache_clear()

    yield config_module.get_settings()

    config_module.get_settings.cache_clear()


def test_load_template_positions(settings, positions_data):
    loaded = certgen.load_template_positions(settings.POSITIONS_FILE)
    assert loaded == positions_data


def test_save_template_positions(tmp_path):
    positions_file = tmp_path / "sub" / "template_positions.json"
    data = {"participation": {"template_file": "foo.pdf"}}

    certgen.save_template_positions(str(positions_file), data)

    assert positions_file.exists()
    assert certgen.load_template_positions(str(positions_file)) == data


def test_get_available_types(settings, positions_data):
    types = certgen.get_available_types(settings.POSITIONS_FILE)
    assert set(types) == set(positions_data.keys())


def test_calculate_font_size_fits_at_max_size():
    size = certgen.calculate_font_size(
        "Jo NANA", "Helvetica-Bold", max_size=36, min_size=18, max_width=500
    )
    assert size == 36


def test_calculate_font_size_shrinks_for_long_name():
    long_name = "Jean-Baptiste Kokou Mawuli AGBODJOGBE-HOUNSOUNOU"
    size = certgen.calculate_font_size(
        long_name, "Helvetica-Bold", max_size=36, min_size=18, max_width=200
    )
    assert 18 <= size < 36


def test_calculate_font_size_floors_at_min_size():
    very_long_name = "A" * 200
    size = certgen.calculate_font_size(
        very_long_name, "Helvetica-Bold", max_size=36, min_size=18, max_width=50
    )
    assert size == 18


def test_generate_qr_code_returns_png_of_requested_size():
    from PIL import Image
    import io

    data = certgen.generate_qr_code("https://example.com/verifier?code=abc", size=80)

    assert data.startswith(PNG_MAGIC)
    image = Image.open(io.BytesIO(data))
    assert image.size == (80, 80)


def test_generate_certificate_creates_pdf_at_expected_path(settings):
    output_path = certgen.generate_certificate(
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        cert_type="participation",
        cert_id="abc123",
        settings=settings,
    )

    path = Path(output_path)
    assert path.exists()
    assert path.parent == Path(settings.CERTIFS_DIR) / "2026" / "participation"
    assert path.name == "abc123_KOLANI_Julien.pdf"

    reader = PdfReader(str(path))
    assert len(reader.pages) == 1


def test_generate_certificate_copies_extra_pages_unmodified(settings):
    output_path = certgen.generate_certificate(
        name="Mensah",
        first_name="Ama",
        event_name="IndabaX Togo 2020",
        event_date="2020-11-01",
        cert_type="organisation_2020",
        cert_id="def456",
        settings=settings,
    )

    reader = PdfReader(output_path)
    assert len(reader.pages) == 2


def test_generate_certificate_unknown_type_raises(settings):
    with pytest.raises(ValueError):
        certgen.generate_certificate(
            name="Kolani",
            first_name="Julien",
            event_name="IndabaX Togo 2026",
            event_date="2026-03-15",
            cert_type="does-not-exist",
            cert_id="abc123",
            settings=settings,
        )


def test_render_preview_returns_png(settings):
    data = certgen.render_preview(
        cert_type="participation",
        test_name="Jean-Baptiste Kokou Mawuli AGBODJOGBE-HOUNSOUNOU",
        settings=settings,
    )

    assert data.startswith(PNG_MAGIC)

    from PIL import Image
    import io

    image = Image.open(io.BytesIO(data))
    assert image.size[0] > 0 and image.size[1] > 0


def test_render_preview_with_overrides_does_not_persist(settings):
    original = certgen.load_template_positions(settings.POSITIONS_FILE)

    data = certgen.render_preview(
        cert_type="participation",
        test_name="Test Override",
        settings=settings,
        overrides={"qr_size": 200, "name_position": {"x": 10, "y": 10}},
    )

    assert data.startswith(PNG_MAGIC)
    assert certgen.load_template_positions(settings.POSITIONS_FILE) == original


def test_merge_config_partial_position_override():
    base = {"name_position": {"x": 100, "y": 200}, "qr_size": 80}

    merged = certgen._merge_config(base, {"name_position": {"x": 999}})

    assert merged["name_position"] == {"x": 999, "y": 200}
    assert merged["qr_size"] == 80
    assert base["name_position"] == {"x": 100, "y": 200}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("DUPONT_Jean", "DUPONT_Jean"),
        ("DUPONT_Jean Paul", "DUPONT_Jean_Paul"),
        ("KOLANI_Jean/Paul", "KOLANI_Jean_Paul"),
        ("../../ETC_passwd", "ETC_passwd"),
        ("N'GUESSAN_Hélène", "N_GUESSAN_Hélène"),
        ("///", "certificat"),
    ],
)
def test_safe_filename_part(raw, expected):
    assert certgen._safe_filename_part(raw) == expected


def test_generate_certificate_with_slash_in_name_stays_in_certifs_dir(settings):
    """Regression: "Jean/Paul" was used as-is in the filename, so the write
    failed (missing "Jean" directory) and the row ended in error."""
    output_path = Path(certgen.generate_certificate(
        name="Kolani", first_name="Jean/Paul", event_name="Evt", event_date="2026-03-15",
        cert_type="participation", cert_id="slash1", settings=settings,
    ))

    assert output_path.exists()
    assert output_path.name == "slash1_KOLANI_Jean_Paul.pdf"
    assert output_path.parent == Path(settings.CERTIFS_DIR) / "2026" / "participation"
