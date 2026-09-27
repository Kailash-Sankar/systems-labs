FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

ENV UV_NO_CONFIG=1

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv sync --no-dev --index-url https://pypi.org/simple

EXPOSE 8000

CMD [".venv/bin/uvicorn", "cap_partition.app:app", "--host", "0.0.0.0", "--port", "8000"]
