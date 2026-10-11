import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.mark.parametrize("enabled", [True, False])
def test_docs_toggle_and_binary_contract(monkeypatch, enabled):
    monkeypatch.setenv("DOCS_ENABLED", str(enabled))
    with TestClient(main.create_app()) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == (200 if enabled else 404)
        if enabled:
            schema = client.get("/openapi.json").json()
            assert schema["info"]["title"] == "PDF Extractor Service"
            assert schema["info"]["version"] == "1.0.0"
            operation = schema["paths"]["/extract"]["post"]
            assert "application/pdf" in operation["requestBody"]["content"]
            assert {"200", "400", "413", "415", "422", "429", "503", "500"} <= operation["responses"].keys()
            assert {"X-Cache", "X-Audit-Id", "X-Request-ID"} <= operation["responses"]["200"]["headers"].keys()
            assert "application/problem+json" in operation["responses"]["429"]["content"]
            assert {"/health/live", "/health/ready"} <= schema["paths"].keys()
        response = client.post("/extract", content=b"", headers={"Content-Type": "application/pdf", "X-Audit-Id": "audit-test"})
        assert response.headers["X-Audit-Id"] == "audit-test"
