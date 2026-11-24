def test_verify_by_code_found(client, sample_certificate):
    cert = sample_certificate["cert"]

    response = client.get(f"/api/verify/{cert['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authentique"
    assert body["details"]["name"] == "Kolani"
    assert body["details"]["first_name"] == "Julien"
    assert body["details"]["event_name"] == "IndabaX Togo 2026"


def test_verify_by_code_not_found(client):
    response = client.get("/api/verify/does-not-exist")

    assert response.status_code == 404


def test_verify_by_file_match(client, sample_certificate):
    pdf_bytes = sample_certificate["pdf_bytes"]

    response = client.post(
        "/api/verify/file",
        files={"file": ("certificate.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authentique"
    assert body["details"]["id"] == sample_certificate["cert"]["id"]


def test_verify_by_file_no_match(client):
    response = client.post(
        "/api/verify/file",
        files={"file": ("other.pdf", b"totally different content", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "altere_ou_inconnu"
