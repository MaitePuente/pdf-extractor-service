FROM ghcr.io/astral-sh/uv:0.11.6 AS uv
FROM python:3.12-slim AS builder

COPY --from=uv /uv /tooling/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/service/.venv/bin:$PATH"

WORKDIR /service
COPY pyproject.toml uv.lock ./
RUN /tooling/uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/service/.venv/bin:$PATH"
WORKDIR /service
# Native extensions and their interpreter remain on the same Python/OS ABI.
COPY --from=builder /service/.venv /service/.venv

COPY app ./app
RUN useradd --no-create-home --uid 10001 extractor \
    && /usr/local/bin/python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip
USER extractor

EXPOSE 8000
CMD ["python", "-m", "app.server"]
