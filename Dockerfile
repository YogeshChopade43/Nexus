# One image: the backend serves the built frontend on port 8000.
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_URL=same-origin npx vite build

FROM python:3.11-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# The built-in web browser: Playwright's headless Chromium and the system libraries it needs.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/browsers
RUN python -m playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*
# Bake the local search models into the image (outside the data volume) so containers never download them.
ENV NEXUS_MODELS_DIR=/app/models
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/models'); \
TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2', cache_dir='/app/models')"
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend-dist

# Run as an ordinary user, not root. It owns only what Nexus writes: the data volume and the model cache.
RUN useradd --uid 10001 --create-home nexus && mkdir -p /app/backend/data && chown -R nexus /app/backend/data /app/models
USER nexus
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/app/backend/data/nexus.db \
    NEXUS_STATIC_DIR=/app/frontend-dist
VOLUME /app/backend/data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host $HOST --port $PORT"]
