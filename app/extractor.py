import pymupdf
from time import perf_counter
from fastapi import HTTPException
from pydantic import BaseModel

from app.markdown import to_markdown


class ExtractionResponse(BaseModel):
    content: str
    page_count: int


def extract_pdf(body: bytes, *, converter=None, timings=None) -> ExtractionResponse:
    start = perf_counter()
    try:
        document = pymupdf.open(stream=body, filetype="pdf")
    except pymupdf.FileDataError as exc:
        raise HTTPException(status_code=400, detail="Invalid PDF document") from exc
    opened = perf_counter()
    with document:
        if document.needs_pass:
            raise HTTPException(
                status_code=400, detail="Password-protected PDFs are not supported"
            )
        page_count = document.page_count
        content = (converter(document) if converter else
                   to_markdown(document, timings=timings))
        converted = perf_counter()
    if timings is not None:
        timings.update(open_ms=(opened - start) * 1000,
                       convert_ms=(converted - opened) * 1000,
                       algorithm_ms=(perf_counter() - start) * 1000)
    started = perf_counter()
    result = ExtractionResponse(content=content, page_count=page_count)
    if timings is not None:
        timings["response_object_ms"] = (perf_counter() - started) * 1000
    return result
