import asyncio

import httpx2
import pymupdf

from app.main import app


def test_health_remains_available_while_pdf_is_converting():
    # A generated text PDF, not a stress fixture. Real conversion, no mocked clock.
    with pymupdf.open() as document:
        for number in range(5):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {number + 1}")
            page.insert_textbox(
                pymupdf.Rect(72, 110, 500, 700),
                "Selectable text and Markdown conversion.\n" * 30,
            )
        body = document.tobytes()

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client:
                extracting = asyncio.create_task(client.post(
                    "/extract", content=body, headers={"Content-Type": "application/pdf"}
                ))
                await asyncio.sleep(0.01)
                try:
                    # With sync conversion in async endpoint, even this heartbeat
                    # cannot run until the entire extraction has completed.
                    assert not extracting.done(), "Conversion blocked the event loop"
                    health = await asyncio.wait_for(client.get("/health"), timeout=2)
                    assert health.status_code == 200
                    assert health.json() == {"status": "ok", "service": "extractor"}
                    assert not extracting.done(), "Health waited for extraction to finish"
                finally:
                    result = await extracting
                assert result.status_code == 200
                assert result.json()["page_count"] == 5
                assert "Selectable text" in result.json()["content"]

    asyncio.run(exercise())


def test_concurrent_conversion_is_rejected_instead_of_queued():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Bounded conversion")
        body = document.tobytes()

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client:
                extracting = asyncio.create_task(client.post(
                    "/extract", content=body, headers={"Content-Type": "application/pdf"}
                ))
                await asyncio.sleep(0.01)
                try:
                    assert not extracting.done()
                    another = await client.post(
                        "/extract", content=body, headers={"Content-Type": "application/pdf"}
                    )
                    assert another.status_code == 503
                    assert (await client.get("/health")).status_code == 200
                finally:
                    result = await extracting
                assert result.status_code == 200
                # Capacity is available again once the first job really finishes.
                again = await client.post(
                    "/extract", content=body, headers={"Content-Type": "application/pdf"}
                )
                assert again.status_code == 200
                assert again.json() == result.json()

    asyncio.run(exercise())


def test_cancellation_does_not_free_capacity_before_cpu_work_finishes():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Cancelled request")
        body = document.tobytes()

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client:
                extracting = asyncio.create_task(client.post(
                    "/extract", content=body, headers={"Content-Type": "application/pdf"}
                ))
                await asyncio.sleep(0.01)
                assert not extracting.done()
                extracting.cancel()
                try:
                    await extracting
                except asyncio.CancelledError:
                    pass
                another = await client.post(
                    "/extract", content=body, headers={"Content-Type": "application/pdf"}
                )
                assert another.status_code == 503
                assert (await client.get("/health")).status_code == 200
        # Lifespan waits for the outstanding worker before disposing its pool.

    asyncio.run(exercise())
