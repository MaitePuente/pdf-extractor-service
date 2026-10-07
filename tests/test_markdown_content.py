import pymupdf
from fastapi.testclient import TestClient

from app.main import app


def test_every_page_keeps_its_raw_text_under_a_markdown_page_heading():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Readable title", fontsize=20, fontname="hebo")
        page.insert_text((72, 120), "Body content with normal font.", fontsize=11)
        page.insert_text((72, 150), "**literal** _name_ [reference] | pipe", fontsize=11)
        page.insert_text((72, 180), "Small annotation must survive.", fontsize=2)
        page = document.new_page()
        page.insert_text((72, 72), "Last page, no content discarded.", fontsize=11)
        # An image-only page remains represented, without image metadata/OCR.
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        image.clear_with(127)
        document.new_page().insert_image(pymupdf.Rect(72, 72, 100, 100), stream=image.tobytes('png'))
        expected = "\n\n".join(
            f"## Página {n + 1}\n\n{page.get_text('text')}"
            for n, page in enumerate(document)
        )
        body = document.tobytes()
    with TestClient(app) as client:
        response = client.post("/extract", content=body, headers={"Content-Type": "application/pdf"})
    assert response.status_code == 200
    result = response.json()
    assert result["page_count"] == 3
    assert "Small annotation must survive." in result["content"]
    assert result["content"] == expected
    assert result["content"].index("Body content") < result["content"].index("Last page")
