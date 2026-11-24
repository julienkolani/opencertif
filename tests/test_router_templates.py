from pathlib import Path


def test_list_types(client, positions_data):
    response = client.get("/api/templates")

    assert response.status_code == 200
    assert response.json() == {"types": list(positions_data.keys())}


def test_get_type(client, positions_data):
    response = client.get("/api/templates/participation")

    assert response.status_code == 200
    assert response.json() == positions_data["participation"]


def test_get_type_unknown_returns_404(client):
    response = client.get("/api/templates/does-not-exist")

    assert response.status_code == 404


def test_update_type_persists_to_disk(client, app_env):
    new_config = {
        "template_file": "Certificat_participation.pdf",
        "name_position": {"x": 400, "y": 280},
        "name_font": "Helvetica-Bold",
        "name_max_size": 40,
        "name_min_size": 20,
        "name_max_width": 550,
        "qr_position": {"x": 60, "y": 60},
        "qr_size": 90,
        "pages": 1,
        "name_page": 1,
    }

    response = client.put("/api/templates/participation", json=new_config)

    assert response.status_code == 200
    assert response.json() == new_config

    from core.certgen import load_template_positions

    persisted = load_template_positions(app_env.POSITIONS_FILE)
    assert persisted["participation"] == new_config


def test_update_type_invalid_body_returns_422(client):
    response = client.put("/api/templates/participation", json={"template_file": "x.pdf"})

    assert response.status_code == 422


def test_preview_type_returns_png(client):
    response = client.get(
        "/api/templates/participation/preview",
        params={"test_name": "Jean-Baptiste Kokou Mawuli AGBODJOGBE-HOUNSOUNOU"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_preview_type_unknown_type_returns_404(client):
    response = client.get(
        "/api/templates/does-not-exist/preview", params={"test_name": "Test"}
    )

    assert response.status_code == 404


def test_preview_type_with_position_overrides_does_not_persist(client, app_env, positions_data):
    response = client.get(
        "/api/templates/participation/preview",
        params={
            "test_name": "Test Override",
            "x": 10,
            "y": 20,
            "qr_x": 5,
            "qr_y": 5,
            "qr_size": 150,
            "name_max_size": 12,
            "name_min_size": 10,
            "name_max_width": 100,
        },
    )

    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")

    # Overrides must not have been written to template_positions.json.
    unchanged = client.get("/api/templates/participation")
    assert unchanged.json() == positions_data["participation"]


def test_preview_type_missing_test_name_returns_422(client):
    response = client.get("/api/templates/participation/preview")

    assert response.status_code == 422


# --- create_template / delete_template ---


def _upload_pdf_bytes() -> bytes:
    import io

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.showPage()
    c.save()
    return buffer.getvalue()


def test_create_template_success(client, app_env):
    response = client.post(
        "/api/templates",
        data={"cert_type": "hackathon-2027"},
        files={"file": ("Certificat_hackathon.pdf", _upload_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["template_file"] == "hackathon-2027_Certificat_hackathon.pdf"
    assert body["name_page"] == 1

    from core.certgen import load_template_positions

    persisted = load_template_positions(app_env.POSITIONS_FILE)
    assert "hackathon-2027" in persisted
    assert (Path(app_env.TEMPLATES_DIR) / "hackathon-2027_Certificat_hackathon.pdf").exists()


def test_create_template_duplicate_returns_400(client):
    response = client.post(
        "/api/templates",
        data={"cert_type": "participation"},
        files={"file": ("x.pdf", _upload_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 400


def test_create_template_rejects_unsafe_cert_type(client, app_env):
    response = client.post(
        "/api/templates",
        data={"cert_type": "../../evil"},
        files={"file": ("x.pdf", _upload_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 400
    # Nothing should have been written outside TEMPLATES_DIR.
    assert not (Path(app_env.TEMPLATES_DIR).parent / "evil").exists()


def test_create_template_sanitizes_path_traversal_in_filename(client, app_env):
    response = client.post(
        "/api/templates",
        data={"cert_type": "safe-type"},
        files={"file": ("../../../evil.pdf", _upload_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    # The traversal-laden filename must have been reduced to its basename.
    assert (Path(app_env.TEMPLATES_DIR) / "safe-type_evil.pdf").exists()
    assert not (Path(app_env.TEMPLATES_DIR).parent.parent / "evil.pdf").exists()


def test_create_template_rejects_non_pdf(client):
    response = client.post(
        "/api/templates",
        data={"cert_type": "not-a-pdf"},
        files={"file": ("x.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400


def test_delete_template_success(client, app_env):
    client.post(
        "/api/templates",
        data={"cert_type": "to-delete"},
        files={"file": ("x.pdf", _upload_pdf_bytes(), "application/pdf")},
    )

    response = client.delete("/api/templates/to-delete")

    assert response.status_code == 200
    from core.certgen import load_template_positions

    assert "to-delete" not in load_template_positions(app_env.POSITIONS_FILE)
    assert not (Path(app_env.TEMPLATES_DIR) / "to-delete_x.pdf").exists()


def test_delete_template_unknown_returns_404(client):
    response = client.delete("/api/templates/does-not-exist")

    assert response.status_code == 404


def test_delete_template_keeps_shared_pdf_file(client, app_env):
    """Deleting a type must not remove the PDF if another type still references it."""
    positions = {
        "type-a": {
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
    }
    client.put("/api/templates/type-a", json=positions["type-a"])
    # "participation" (from the base fixture) already points at the same PDF file.

    response = client.delete("/api/templates/type-a")

    assert response.status_code == 200
    assert (Path(app_env.TEMPLATES_DIR) / "Certificat_participation.pdf").exists()
