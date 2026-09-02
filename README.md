# unmonitarr

Stop Radarr and Sonarr from re-searching and upgrading things you've already
watched.

This script reads watched state from **Plex**, matches each watched movie or
episode to its entry in **Radarr** / **Sonarr**, and unmonitors it (or,
optionally, deletes it). It's meant to run as a one-off or on a schedule —
including inside Docker, with a built-in cron-style scheduler — so your
`*arr` apps stop wasting search/upgrade cycles on media you're done with.

## How matching works

- **Movies** are matched to Radarr using the TMDb ID (falling back to the
  IMDb ID) pulled from Plex's metadata.
- **Episodes** are matched by first resolving the parent show to a Sonarr
  series via its TVDb ID, then matching the specific episode by season and
  episode number.

If a watched item has no match in Radarr/Sonarr (e.g. it isn't tracked
there), it's skipped and logged.

## Safety: dry run by default

**Nothing is changed unless you pass `--apply`.** Every run — dry run or
not — prints exactly what it would do (or did), item by item, followed by a
summary. Run it without `--apply` first and read the output before trusting
it with `--apply`.

## Requirements

The script carries a [PEP 723](https://peps.python.org/pep-0723/) inline
metadata header, so the simplest way to run it is with
[uv](https://docs.astral.sh/uv/), which creates an ephemeral virtualenv with
the right dependencies automatically:

```bash
uv run unmonitarr.py --help
```

Without uv:

```bash
pip install plexapi requests
python unmonitarr.py --help
```

## Configuration

All connection details can be passed as CLI flags or environment variables
(CLI flags win if both are set):

| Env var            | CLI flag           | Required           |
|---------------------|---------------------|---------------------|
| `PLEX_URL`          | `--plex-url`        | Yes                 |
| `PLEX_TOKEN`        | `--plex-token`      | Yes                 |
| `RADARR_URL`        | `--radarr-url`      | Yes, unless `--skip-movies` |
| `RADARR_API_KEY`    | `--radarr-api-key`  | Yes, unless `--skip-movies` |
| `SONARR_URL`        | `--sonarr-url`      | Yes, unless `--skip-shows`  |
| `SONARR_API_KEY`    | `--sonarr-api-key`  | Yes, unless `--skip-shows`  |

Don't know your Plex token? See
[Plex's support article](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

## Flags

| Flag | Default | What it does |
|---|---|---|
| `--apply` | off (dry run) | Actually perform the changes. Without it, the script only prints what it would do. |
| `--movie-library NAME` | `Movies` | Name of the Plex movie library section to scan. |
| `--show-library NAME` | `TV Shows` | Name of the Plex TV library section to scan. |
| `--skip-movies` | off | Don't process movies / Radarr at all. |
| `--skip-shows` | off | Don't process TV episodes / Sonarr at all. |
| `--hide-already-unmonitored` | off | Suppress the "already unmonitored" log line. **Turn this on if you also run [Maintainerr](https://github.com/jorenn92/Maintainerr)** (or anything else that unmonitors/cleans up watched media on its own): once Maintainerr has already unmonitored something, this script would otherwise keep re-logging it as "already unmonitored" on every single scheduled run, which is just noise. If you're *not* running something like Maintainerr, leave this off so you get a full record of what's already handled. |
| `--delete-movies` | off | Instead of unmonitoring, remove the watched movie from Radarr entirely. |
| `--delete-episodes` | off | Delete the watched episode's file from Sonarr and unmonitor the episode. Sonarr has no concept of removing a single episode entry (only its file), so the episode stays listed but file-less and unmonitored. |
| `--delete-files` | off | Only relevant with `--delete-movies`: also delete the movie's files from disk. Without it, the movie is removed from Radarr but its files are left on disk (handy if something else, e.g. Maintainerr, handles physical cleanup). |

## Usage examples

```bash
# Preview only (default) - movies and shows
uv run unmonitarr.py

# Only movies, preview only
uv run unmonitarr.py --skip-shows

# Actually unmonitor watched items
uv run unmonitarr.py --apply

# Scheduled run alongside Maintainerr - quiet, unmonitor only
uv run unmonitarr.py --apply --hide-already-unmonitored

# Delete watched movies from Radarr (keep files) and delete watched
# episode files from Sonarr
uv run unmonitarr.py --apply --delete-movies --delete-episodes

# Also wipe movie files from disk when deleting from Radarr
uv run unmonitarr.py --apply --delete-movies --delete-files

# Non-default Plex library names
uv run unmonitarr.py --movie-library "Films" --show-library "Series"
```

## Running in Docker

The image runs the script on a **schedule using standard cron syntax**, via
a small built-in Python scheduler (no system cron daemon required).

### docker-compose

1. Copy `.env.example` to `.env` and fill in your Plex/Radarr/Sonarr
   details.
2. Adjust `CRON_SCHEDULE` / `SCRIPT_ARGS` in `docker-compose.yml` if needed.
3. `docker compose up -d`

```yaml
services:
  unmonitarr:
    image: ghcr.io/stokkie90/unmonitarr:latest
    container_name: unmonitarr
    restart: unless-stopped
    env_file:
      - .env
    environment:
      CRON_SCHEDULE: "0 3 * * *"                              # daily at 03:00
      SCRIPT_ARGS: "--apply --hide-already-unmonitored"
      RUN_ON_START: "false"
```

### Docker environment variables

| Variable | Default | Description |
|---|---|---|
| `CRON_SCHEDULE` | `0 3 * * *` | Standard 5-field cron expression for when to run. |
| `SCRIPT_ARGS` | `--apply --hide-already-unmonitored` | Arguments passed to `unmonitarr.py` on each scheduled run (space-separated, shell-quoted). |
| `RUN_ON_START` | `false` | Set to `true` to also run once immediately when the container starts, in addition to the schedule. |
| `PLEX_URL`, `PLEX_TOKEN`, `RADARR_URL`, `RADARR_API_KEY`, `SONARR_URL`, `SONARR_API_KEY` | — | Connection details, as above. |

### Plain `docker run`

```bash
docker run -d \
  --name unmonitarr \
  --restart unless-stopped \
  -e PLEX_URL=http://plex:32400 \
  -e PLEX_TOKEN=xxxx \
  -e RADARR_URL=http://radarr:7878 \
  -e RADARR_API_KEY=xxxx \
  -e SONARR_URL=http://sonarr:8989 \
  -e SONARR_API_KEY=xxxx \
  -e CRON_SCHEDULE="0 3 * * *" \
  -e SCRIPT_ARGS="--apply --hide-already-unmonitored" \
  ghcr.io/stokkie90/unmonitarr:latest
```

## Building the image yourself

```bash
docker build -t unmonitarr .
```

CI (`.github/workflows/docker-publish.yml`) builds and publishes
`ghcr.io/stokkie90/unmonitarr` (linux/amd64 + linux/arm64) on every push
to `main` and on version tags.

## Roadmap

- [ ] Telegram notifications summarizing each run (what was unmonitored /
      deleted, and any items that failed to match).

## Disclaimer

This talks to Radarr/Sonarr's write APIs and, with `--delete-movies`,
`--delete-episodes`, or `--delete-files`, can delete data. Always run
without `--apply` first and check the output. No warranty; use at your own
risk.
