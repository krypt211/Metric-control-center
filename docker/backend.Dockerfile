FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
COPY backend ./backend
COPY services ./services
COPY frontend/lib/metric-registry.json ./frontend/lib/metric-registry.json
COPY workers ./workers
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps '.[workers]' && useradd --uid 10001 --create-home app
USER app
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
