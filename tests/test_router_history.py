def test_history_empty(client):
    response = client.get("/api/history")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": 20}


def test_history_lists_seeded_certificate(client, sample_certificate):
    response = client.get("/api/history")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == sample_certificate["cert"]["id"]


def test_history_filters_by_search(client, sample_certificate):
    response = client.get("/api/history", params={"search": "Kolani"})
    assert response.json()["total"] == 1

    response = client.get("/api/history", params={"search": "NoMatch"})
    assert response.json()["total"] == 0


def test_history_filters_by_cert_type(client, sample_certificate):
    response = client.get("/api/history", params={"cert_type": "organisation_2020"})

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_history_filters_by_year(client, sample_certificate):
    response = client.get("/api/history", params={"year": "2025"})
    assert response.json()["total"] == 0

    response = client.get("/api/history", params={"year": "2026"})
    assert response.json()["total"] == 1


def test_history_pagination_params(client, sample_certificate):
    response = client.get("/api/history", params={"page": 2, "per_page": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["per_page"] == 1
    assert body["items"] == []
