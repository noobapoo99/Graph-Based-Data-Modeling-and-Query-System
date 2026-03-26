FROM python:3.11-slim

# Disables Python buffering because container logs should appear in real time during local development and production debugging.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Installs dependencies first because Docker can reuse this layer when only application code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copies the backend source because the container needs the FastAPI app and ingestion code at runtime.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
