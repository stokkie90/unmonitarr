FROM python:3.12-slim

WORKDIR /app

# Dependencies are declared once, in unmonitarr.py's PEP 723 header, but
# we install them normally here so the container doesn't need internet
# access (or uv) at runtime.
COPY unmonitarr.py scheduler.py ./
RUN pip install --no-cache-dir plexapi requests croniter \
    && chmod +x unmonitarr.py scheduler.py

ENV PYTHONUNBUFFERED=1 \
    CRON_SCHEDULE="0 3 * * *" \
    SCRIPT_ARGS="--apply --hide-already-unmonitored" \
    RUN_ON_START="false"

ENTRYPOINT ["python", "scheduler.py"]
