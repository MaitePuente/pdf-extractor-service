from fastapi.testclient import TestClient
from fastapi import HTTPException, Request

from app.main import app
from app.worker import ExtractionWorker


def test_request_id_is_generated_and_echoed_on_every_health_request():
    with TestClient(app) as client:
        first = client.get("/health")
        second = client.get("/health", headers={"X-Request-ID": "teacher-check-1"})
    assert first.status_code == second.status_code == 200
    assert first.headers["X-Request-ID"]
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert second.headers["X-Request-ID"] == "teacher-check-1"
    assert second.headers["X-Audit-Id"] == "teacher-check-1"


def test_invalid_pdf_uses_problem_details_and_correlates_error():
    with TestClient(app) as client:
        response = client.post(
            "/extract", content=b"not a PDF",
            headers={"Content-Type": "application/pdf", "X-Request-ID": "invalid-pdf-1"},
        )
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-Request-ID"] == "invalid-pdf-1"
    problem = response.json()
    assert problem["type"] == "/errors/invalid-pdf"
    assert problem["status"] == 400
    assert problem["detail"] == "Body must start with %PDF"
    assert problem["instance"].startswith("/extract")
    assert problem["request_id"] == "invalid-pdf-1"


def test_public_errors_use_problem_details_and_bounded_request_ids(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    from app.main import create_app

    with TestClient(create_app()) as client:
        cases = [
            (b"x", "text/plain", 415),
            (b"", "application/pdf", 400),
        ]
        for body, media, expected in cases:
            result = client.post("/extract", content=body, headers={"Content-Type": media, "X-Request-ID": "bad\nvalue"})
            assert result.status_code == expected
            assert result.headers["content-type"] == "application/problem+json"
            assert result.json()["request_id"] == result.headers["X-Request-ID"]
            assert "\n" not in result.headers["X-Request-ID"]
        large = client.post("/extract", content=b"%PDF" + b"x" * 1048576, headers={"Content-Type": "application/pdf"})
        assert large.status_code == 413
        assert large.headers["content-type"] == "application/problem+json"


def test_validation_errors_hide_input_and_use_problem_details():
    from app.main import create_app
    application = create_app()

    @application.get("/validation-probe/{value}")
    def validation_probe(value: int):
        return {"value": value}

    with TestClient(application) as client:
        result = client.get("/validation-probe/secret-token")
    assert result.status_code == 422
    assert result.headers["content-type"] == "application/problem+json"
    assert "secret-token" not in result.text


def test_unexpected_errors_are_sanitized_and_correlated():
    from app.main import create_app
    application = create_app()

    @application.get("/failure-probe")
    def failure_probe(request: Request):
        raise RuntimeError("password=private-host-path")

    with TestClient(application, raise_server_exceptions=False) as client:
        result = client.get("/failure-probe", headers={"X-Request-ID": "failure-1"})
    assert result.status_code == 500
    assert result.headers["content-type"] == "application/problem+json"
    assert result.headers["X-Request-ID"] == "failure-1"
    assert result.headers["X-Audit-Id"] == "failure-1"
    assert result.json()["request_id"] == "failure-1"
    assert "private-host-path" not in result.text


def test_worker_unavailable_is_problem_503(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")
    from app.main import create_app

    async def unavailable(self, body, *, profile=None):
        raise HTTPException(503, "Extraction worker unavailable")

    monkeypatch.setattr(ExtractionWorker, "extract", unavailable)
    with TestClient(create_app()) as client:
        result = client.post("/extract", content=b"%PDF-synthetic", headers={"Content-Type": "application/pdf"})
    assert result.status_code == 503
    assert result.headers["content-type"] == "application/problem+json"
    assert result.json()["type"] == "/errors/service-unavailable"
    assert result.json()["request_id"] == result.headers["X-Request-ID"]
