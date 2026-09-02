#!/usr/bin/env python3
"""
scheduler.py

Tiny cron-syntax scheduler used by the Docker image to run unmonitarr.py
on a schedule inside a single long-running container (no system cron daemon
needed).

Environment variables:
    CRON_SCHEDULE   Standard 5-field cron expression (default: "0 3 * * *",
                     i.e. once a day at 03:00).
    SCRIPT_ARGS      Arguments passed to unmonitarr.py, shell-quoted
                     (default: "--apply"). Plex/Radarr/Sonarr connection
                     details are read by unmonitarr.py itself from the
                     PLEX_URL / PLEX_TOKEN / RADARR_URL / RADARR_API_KEY /
                     SONARR_URL / SONARR_API_KEY environment variables.
    RUN_ON_START     "true" to run once immediately at container startup in
                     addition to the schedule (default: "false").
"""

import os
import shlex
import subprocess
import sys
import time
from datetime import datetime

from croniter import croniter

CRON_SCHEDULE = os.environ.get("CRON_SCHEDULE", "0 3 * * *")
SCRIPT_ARGS = shlex.split(os.environ.get("SCRIPT_ARGS", "--apply"))
RUN_ON_START = os.environ.get("RUN_ON_START", "false").strip().lower() == "true"
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unmonitarr.py")


def run_once():
    cmd = [sys.executable, SCRIPT_PATH] + SCRIPT_ARGS
    print(f"[scheduler] {datetime.now().isoformat()} running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd)
    print(f"[scheduler] run finished with exit code {result.returncode}", flush=True)


def main():
    print(f"[scheduler] cron schedule: {CRON_SCHEDULE!r}", flush=True)
    print(f"[scheduler] script args:   {SCRIPT_ARGS}", flush=True)

    if not croniter.is_valid(CRON_SCHEDULE):
        sys.exit(f"[scheduler] invalid CRON_SCHEDULE: {CRON_SCHEDULE!r}")

    if RUN_ON_START:
        run_once()

    itr = croniter(CRON_SCHEDULE, datetime.now())
    while True:
        next_run = itr.get_next(datetime)
        sleep_seconds = max((next_run - datetime.now()).total_seconds(), 0)
        print(f"[scheduler] next run at {next_run.isoformat()} (sleeping {int(sleep_seconds)}s)", flush=True)
        time.sleep(sleep_seconds)
        run_once()


if __name__ == "__main__":
    main()
