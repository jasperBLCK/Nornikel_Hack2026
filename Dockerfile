# --- Stage 1: build React frontend -----------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# --- Stage 2: Python app -----------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

COPY ingest/requirements.txt ingest-requirements.txt
COPY search/requirements.txt search-requirements.txt
RUN pip install --no-cache-dir -r ingest-requirements.txt -r search-requirements.txt \
    uvicorn fastapi

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-rus p7zip-full \
    && rm -rf /var/lib/apt/lists/*

COPY app/ app/
COPY ingest/ ingest/
COPY search/ search/
COPY run_pipeline.py prepare_corpus.py ./
COPY --from=frontend /build/dist frontend/dist

ENV QDRANT_PATH=/data/qdrant_data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
