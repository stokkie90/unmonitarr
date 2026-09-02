FROM python:3.14-slim

WORKDIR /app

# Dependencies are also declared in unmonitarr.py's PEP 723 header (for
# `uv run` outside Docker), but the image installs from the pinned
# requirements.txt instead, so the container doesn't need internet access
# (or uv) at runtime, and so Dependabot has pinned versions to track.
COPY unmonitarr.py scheduler.py requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && chmod +x unmonitarr.py scheduler.py

ENV PYTHONUNBUFFERED=1 \
    CRON_SCHEDULE="0 3 * * *" \
    SCRIPT_ARGS="--apply --hide-already-unmonitored" \
    RUN_ON_START="false"

ENTRYPOINT ["python", "scheduler.py"]
