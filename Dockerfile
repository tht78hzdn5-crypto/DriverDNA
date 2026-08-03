FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir ".[ui,pg]" \
    && python -m compileall -q /app/src/

ENV PORT=8080

CMD ["sh", "-c", "exec driverdna ui --host 0.0.0.0 --port $PORT --db \"$DRIVERDNA_DATABASE_URL\""]
