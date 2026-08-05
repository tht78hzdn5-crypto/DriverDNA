# DriverDNA container — SQLite backend on a mounted volume.
#
# The production deployment of record is a systemd service on an Oracle VM
# (see deploy/driverdna.service and docs/DEPLOY-RUNBOOK.md, SPEC.md A40). This
# Dockerfile is the optional/local container path; it is NOT built by CI (the
# Cloud Run workflow was retired with A40). It carries no Postgres driver — the
# store is a SQLite file on the /data volume, which must be persistent.
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

# ui = FastAPI/uvicorn + upload + BYOK crypto; ai-gemini = the default coach/
# chat provider. No pg extra: this image is SQLite-only.
RUN pip install --no-cache-dir ".[ui,ai-gemini]" \
    && python -m compileall -q /app/src/

# The store and its raw-blob sidecar both live on the mounted volume so they
# survive container restarts. Mount a persistent volume at /data.
VOLUME ["/data"]
ENV PORT=8080 \
    DRIVERDNA_DATABASE_URL=/data/driverdna.db \
    DRIVERDNA_BLOB_ROOT=/data/driverdna.db.blobs

# --host 0.0.0.0 trips the auth interlock: DRIVERDNA_SESSION_SECRET (or the
# DRIVERDNA_ACCESS_TOKEN fallback) MUST be set in the environment or the app
# refuses to start. That is the interlock working as designed, not a bug.
CMD ["sh", "-c", "exec driverdna ui --host 0.0.0.0 --port $PORT --db \"$DRIVERDNA_DATABASE_URL\""]
