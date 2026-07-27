FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir ".[ui,pg]"

ENV PORT=8080

CMD driverdna ui --host 0.0.0.0 --port $PORT --db "$DRIVERDNA_DATABASE_URL"
