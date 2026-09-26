# ── Stage 1: build the War Room SPA ─────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /app/market_sentiment_tool
COPY market_sentiment_tool/package.json market_sentiment_tool/package-lock.json ./
RUN npm ci
COPY market_sentiment_tool/ ./
# Public by design (browser-side Supabase URL + publishable key). Same-origin API.
ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_PUBLISHABLE_KEY=""
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY \
    VITE_API_BASE_URL=""
RUN npm run build

# ── Stage 2: Python runtime (API + scheduled jobs share this image) ────────
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml
COPY tradehub/ ./tradehub/
COPY shared/ ./shared/
COPY market_sentiment_tool/backend/ ./market_sentiment_tool/backend/
COPY --from=frontend-build /app/market_sentiment_tool/dist ./market_sentiment_tool/dist
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn tradehub.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
