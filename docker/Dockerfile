# carddav2fritzbox — minimal Alpine-based delivery image.
# Installs ONLY the sync's runtime dependencies (no dev tools).
FROM python:3.13-alpine

WORKDIR /app

# Runtime requirements only (research.md §1): requests, vobject, Pillow.
RUN pip install --no-cache-dir \
    "requests>=2.28.0" \
    "vobject>=0.9.6" \
    "Pillow>=9.0.0"

COPY src/ ./src/
COPY docker/entrypoint.py docker/notify.py ./docker/

# Non-root: the sync only needs outbound network plus the read-only config mount.
RUN addgroup -S syncer && adduser -S -G syncer syncer && chown -R syncer:syncer /app
USER syncer

ENTRYPOINT ["python3", "/app/docker/entrypoint.py"]
