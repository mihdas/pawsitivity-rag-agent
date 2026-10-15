# ---- build stage: install dependencies and download the embedding model ----
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 FASTEMBED_CACHE_PATH=/models
WORKDIR /src
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt
ENV PYTHONPATH=/install/lib/python3.12/site-packages
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}')"

# ---- runtime stage ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 FASTEMBED_CACHE_PATH=/models HF_HUB_OFFLINE=1
RUN useradd --create-home --uid 10001 app
COPY --from=build /install /usr/local
COPY --from=build --chown=app /models /models
WORKDIR /app
COPY --chown=app app ./app
COPY --chown=app scripts ./scripts
COPY --chown=app config ./config
COPY --chown=app knowledge ./knowledge
COPY --chown=app evals ./evals
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
