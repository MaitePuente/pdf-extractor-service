import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "extractor"}


def make_pdf() -> bytes:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 100), "Introduction", fontname="hebo", fontsize=20)
        page.insert_text((72, 150), "First page body text.", fontsize=11)
        page = document.new_page()
        page.insert_text((72, 100), "Second page body text.", fontsize=11)
        return document.tobytes()


def test_extract_returns_markdown_and_page_count():
    with TestClient(app) as client:
        response = client.post(
            "/extract", content=make_pdf(), headers={"Content-Type": "application/pdf"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert set(data) == {"content", "page_count"}
    assert data["page_count"] == 2
    assert data["content"].startswith("## Página 1\n\n")
    assert "## Página 2\n\n" in data["content"]
    assert "Introduction" in data["content"]
    assert "First page body text." in data["content"]
    assert "Second page body text." in data["content"]
    assert data["content"].index("First page") < data["content"].index("Second page")


def test_empty_body_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/extract", content=b"", headers={"Content-Type": "application/pdf"}
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "PDF body must not be empty"}


def test_non_pdf_body_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/extract", content=b"not a PDF", headers={"Content-Type": "application/pdf"}
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Body must start with %PDF"}


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/json", "multipart/form-data", None]
)
def test_wrong_or_missing_content_type_is_rejected(content_type):
    headers = {"Content-Type": content_type} if content_type else {}
    with TestClient(app) as client:
        response = client.post("/extract", content=make_pdf(), headers=headers)

    assert response.status_code == 415
    assert response.json() == {"detail": "Content-Type must be application/pdf"}


def test_pdf_signature_alone_is_not_a_valid_pdf():
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            content=b"%PDF-1.7\ninvalid data",
            headers={"Content-Type": "application/pdf"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid PDF document"}


def test_password_protected_pdf_is_rejected():
    with pymupdf.open(stream=make_pdf(), filetype="pdf") as document:
        encrypted = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="reader-password",
        )
    with TestClient(app) as client:
        response = client.post(
            "/extract", content=encrypted, headers={"Content-Type": "application/pdf"}
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Password-protected PDFs are not supported"}


def test_image_only_pdf_does_not_run_ocr():
    with pymupdf.open() as source:
        page = source.new_page()
        page.insert_text((72, 100), "RASTER TEXT MUST NOT BE RECOGNIZED", fontsize=16)
        image = page.get_pixmap().tobytes("png")
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_image(page.rect, stream=image)
        body = document.tobytes()

    with TestClient(app) as client:
        response = client.post(
            "/extract", content=body, headers={"Content-Type": "application/pdf"}
        )

    assert response.status_code == 200
    assert response.json()["page_count"] == 1
    assert "RASTER TEXT" not in response.json()["content"]


def test_pdf_media_type_is_case_insensitive_and_accepts_parameters():
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            content=make_pdf(),
            headers={"Content-Type": "Application/PDF; version=1.7"},
        )

    assert response.status_code == 200
    assert response.json()["page_count"] == 2
