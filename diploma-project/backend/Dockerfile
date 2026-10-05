FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY constraints-linux.txt ./

RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r constraints-linux.txt

COPY pyproject.toml ./
COPY app ./app

RUN --mount=type=cache,target=/root/.cache/pip python -m pip install --no-deps . \
    && python -m pip check \
    && useradd --create-home --uid 10001 appuser

USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
