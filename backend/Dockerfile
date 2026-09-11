FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
# S4 management validates independently produced quality reports offline.
COPY evals/events ./evals/events

# Build identity, surfaced by /healthz so a stale deploy is obvious.
# Pass with: fly deploy --build-arg GIT_SHA=$(git rev-parse --short HEAD)
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
