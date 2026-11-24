def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_expected_routes(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    assert schema["info"]["title"] == "OpenCertif API"
    assert schema["info"]["version"] == "1.0.0"

    paths = schema["paths"]
    assert "/api/certificates/generate" in paths
    assert "/api/certificates/batch" in paths
    assert "/api/certificates/{cert_id}/pdf" in paths
    assert "/api/verify/{code}" in paths
    assert "/api/verify/file" in paths
    assert "/api/history" in paths
    assert "/api/templates" in paths
    assert "/api/templates/{cert_type}" in paths
    assert "/api/templates/{cert_type}/preview" in paths


def test_cors_allows_configured_origin(client, app_env):
    origin = app_env.CORS_ORIGINS[0]

    response = client.get("/api/health", headers={"Origin": origin})

    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_other_origin(client):
    response = client.get("/api/health", headers={"Origin": "https://not-allowed.example.com"})

    assert response.headers.get("access-control-allow-origin") is None
