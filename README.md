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

The pinned `requirements.txt` in this repo (which also includes `croniter`,
needed by `scheduler.py`) is what the Docker image installs from, and is
what Dependabot tracks for updates; it's not needed for plain `uv run` or
`pip install` usage above.

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

Every flag also has an equivalent environment variable, so the container
(or a systemd unit, or anything else that's more comfortable setting env
vars than CLI args) can be configured without touching `SCRIPT_ARGS` at
all. Boolean env vars accept `1`/`true`/`yes`/`on`, case-insensitive. A
boolean env var can only turn a flag on; there's no env var that forces
one off, so to disable something you set from the environment, unset the
variable rather than expecting the CLI's absence to override it.

| Flag | Env var | Default | What it does |
|---|---|---|---|
| `--apply` | `APPLY` | off (dry run) | Actually perform the changes. Without it, the script only prints what it would do. |
| `--movie-library NAME` | `MOVIE_LIBRARY` | `Movies` | Name of the Plex movie library section to scan. |
| `--show-library NAME` | `SHOW_LIBRARY` | `TV Shows` | Name of the Plex TV library section to scan. |
| `--skip-movies` | `SKIP_MOVIES` | off | Don't process movies / Radarr at all. |
| `--skip-shows` | `SKIP_SHOWS` | off | Don't process TV episodes / Sonarr at all. |
| `--hide-already-unmonitored` | `HIDE_ALREADY_UNMONITORED` | off | Suppress the "already unmonitored" log line. **Turn this on if you also run [Maintainerr](https://github.com/jorenn92/Maintainerr)** (or anything else that unmonitors/cleans up watched media on its own): once Maintainerr has already unmonitored something, this script would otherwise keep re-logging it as "already unmonitored" on every single scheduled run, which is just noise. If you're *not* running something like Maintainerr, leave this off so you get a full record of what's already handled. |
| `--delete-movies` | `DELETE_MOVIES` | off | Instead of unmonitoring, remove the watched movie from Radarr entirely. |
| `--delete-episodes` | `DELETE_EPISODES` | off | Delete the watched episode's file from Sonarr and unmonitor the episode. Sonarr has no concept of removing a single episode entry (only its file), so the episode stays listed but file-less and unmonitored. |
| `--delete-files` | `DELETE_FILES` | off | Only relevant with `--delete-movies`: also delete the movie's files from disk. Without it, the movie is removed from Radarr but its files are left on disk (handy if something else, e.g. Maintainerr, handles physical cleanup). |
| `--unmonitor-after-days N` | `UNMONITOR_AFTER_DAYS` | `0` | Only unmonitor a watched item once it's been watched (per Plex's `lastViewedAt`) at least `N` days. `0` means immediately, the original behavior. |
| `--delete-after-days N` | `DELETE_AFTER_DAYS` | `0` | Only relevant with `--delete-movies`/`--delete-episodes`: only delete once watched at least `N` days ago. This still deletes an item that was already unmonitored by an earlier run, since deletion doesn't check the current monitored state, only how long ago it was watched. Lets you run one schedule that unmonitors quickly and deletes much later. |
| `--filter TEXT` | `FILTER` | off | Only process movies/shows whose title contains `TEXT` (case-insensitive). Mainly for testing against a single movie or show without touching the rest of the library. |

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

# Unmonitor immediately (default), but only delete once something's sat
# watched for 90+ days. An item already unmonitored by an earlier run
# still gets deleted once it crosses the threshold.
uv run unmonitarr.py --apply --delete-movies --delete-episodes --delete-after-days 90

# Wait a week after watching before even unmonitoring
uv run unmonitarr.py --apply --unmonitor-after-days 7

# Test against one title only, without touching the rest of the library
uv run unmonitarr.py --filter "The Matrix"

# Non-default Plex library names
uv run unmonitarr.py --movie-library "Films" --show-library "Series"
```

## Running in Docker

The image runs the script on a **schedule using standard cron syntax**, via
a small built-in Python scheduler (no system cron daemon required).

### docker-compose

1. Copy `.env.example` to `.env` and fill in your Plex/Radarr/Sonarr
   details.
2. Adjust `CRON_SCHEDULE` and the `unmonitarr.py` flag env vars (`APPLY`,
   `HIDE_ALREADY_UNMONITORED`, etc.) in `docker-compose.yml` if needed.
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
      RUN_ON_START: "false"
      APPLY: "true"
      HIDE_ALREADY_UNMONITORED: "true"
```

### Docker environment variables

| Variable | Default | Description |
|---|---|---|
| `CRON_SCHEDULE` | `0 3 * * *` | Standard 5-field cron expression for when to run. |
| `RUN_ON_START` | `false` | Set to `true` to also run once immediately when the container starts, in addition to the schedule. |
| `SCRIPT_ARGS` | `""` (unset) | Optional: arguments passed to `unmonitarr.py` on each scheduled run (space-separated, shell-quoted), e.g. `"--apply --skip-shows"`. Anything expressible this way can also be set as its own env var (see the [Flags](#flags) table); both mechanisms add up rather than one overriding the other. |
| `APPLY`, `HIDE_ALREADY_UNMONITORED`, `SKIP_MOVIES`, `SKIP_SHOWS`, `DELETE_MOVIES`, `DELETE_EPISODES`, `DELETE_FILES`, `MOVIE_LIBRARY`, `SHOW_LIBRARY`, `UNMONITOR_AFTER_DAYS`, `DELETE_AFTER_DAYS`, `FILTER` | see [Flags](#flags) | One env var per `unmonitarr.py` flag, so the container can be fully configured without building a `SCRIPT_ARGS` string. |
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
  -e APPLY=true \
  -e HIDE_ALREADY_UNMONITORED=true \
  ghcr.io/stokkie90/unmonitarr:latest
```

### Running `unmonitarr.py` directly in the container (bypassing the scheduler)

The image's `ENTRYPOINT` is fixed to `scheduler.py`, so a plain
`docker run ... unmonitarr python unmonitarr.py --help` silently runs the
scheduler instead. It appends `python unmonitarr.py --help` as extra,
ignored arguments to the entrypoint rather than erroring. To run the
script directly, for example for a one-off manual dry run, override the
entrypoint:

```bash
docker run --rm --env-file .env --entrypoint python unmonitarr:latest unmonitarr.py
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
