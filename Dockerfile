# One image: the backend serves the built frontend on port 8000.
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_URL=same-origin npx vite build

FROM python:3.11-slim
# Node (npx) and uv (uvx) launch most local MCP servers.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Bake the local search models into the image (outside the data volume) so containers never download them.
ENV NEXUS_MODELS_DIR=/app/models
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/models'); \
TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2', cache_dir='/app/models')"
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend-dist

ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/app/backend/data/nexus.db \
    NEXUS_STATIC_DIR=/app/frontend-dist
VOLUME /app/backend/data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host $HOST --port $PORT"]
