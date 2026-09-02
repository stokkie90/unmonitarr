#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "plexapi",
#     "requests",
# ]
# ///
"""
unmonitarr.py

One-off script: scans Plex for watched movies and TV episodes, then
unmonitors (or optionally deletes) the matching item in Radarr (movie) or
Sonarr (episode) so it won't be re-searched/upgraded once you've watched it.

Matching:
    Movies  -> matched to Radarr by tmdbId (falls back to imdbId) pulled
               from Plex's `guids` list.
    Episodes-> the parent show is matched to a Sonarr series by tvdbId,
               then the specific episode is matched by season/episode number.

Safety:
    Dry-run is the DEFAULT. Nothing is changed in Radarr/Sonarr unless you
    pass --apply. Every run prints exactly what it would do / did.

Requirements:
    This script carries a uv inline metadata header, so the easiest way to
    run it is via uv (https://docs.astral.sh/uv/), which creates an
    ephemeral venv with the right dependencies automatically:

        uv run unmonitarr.py [args...]

    or, if it's executable (chmod +x):

        ./unmonitarr.py [args...]

    Without uv, install deps manually and run with plain python:

        pip install plexapi requests
        python unmonitarr.py [args...]

Configuration (env vars, or the equivalent CLI flags which take priority):
    PLEX_URL                    e.g. http://localhost:32400
    PLEX_TOKEN                  your Plex auth token
    RADARR_URL                  e.g. http://localhost:7878
    RADARR_API_KEY
    SONARR_URL                  e.g. http://localhost:8989
    SONARR_API_KEY
    MOVIE_LIBRARY               same as --movie-library (default "Movies")
    SHOW_LIBRARY                same as --show-library (default "TV Shows")
    SKIP_MOVIES                 same as --skip-movies (1/true/yes/on)
    SKIP_SHOWS                  same as --skip-shows (1/true/yes/on)
    APPLY                       same as --apply (1/true/yes/on)
    HIDE_ALREADY_UNMONITORED    same as --hide-already-unmonitored (1/true/yes/on)
    DELETE_MOVIES                same as --delete-movies (1/true/yes/on)
    DELETE_EPISODES             same as --delete-episodes (1/true/yes/on)
    DELETE_FILES                same as --delete-files (1/true/yes/on)
    UNMONITOR_AFTER_DAYS         same as --unmonitor-after-days (integer, default 0)
    DELETE_AFTER_DAYS           same as --delete-after-days (integer, default 0)
    FILTER                      same as --filter (substring, case-insensitive)

    Every on/off flag's CLI form can only turn it ON; it never overrides an
    env var of "true" back to off. To force something off, unset or clear
    the env var rather than relying on the CLI flag's absence.

Usage (examples shown with uv; drop "uv run" if using plain python):
    # Preview only (default) - movies and shows
    uv run unmonitarr.py

    # Only movies, preview only
    uv run unmonitarr.py --skip-shows

    # Actually flip the monitored flag off
    uv run unmonitarr.py --apply

    # Running alongside Maintainerr: hide the noisy "already unmonitored"
    # lines you'd otherwise get on every scheduled run
    uv run unmonitarr.py --apply --hide-already-unmonitored

    # Delete watched movies from Radarr entirely (files kept unless
    # --delete-files is also passed), and delete watched episode files
    # from Sonarr (also unmonitors the episode so it isn't re-grabbed)
    uv run unmonitarr.py --apply --delete-movies --delete-episodes

    # Unmonitor immediately (default), but only actually delete once
    # something has sat watched for 90+ days. An item already unmonitored
    # by an earlier run still gets deleted once it crosses the threshold.
    uv run unmonitarr.py --apply --delete-movies --delete-episodes --delete-after-days 90

    # Wait 7 days after watching before even unmonitoring
    uv run unmonitarr.py --apply --unmonitor-after-days 7

    # Test against a single title without touching anything else
    uv run unmonitarr.py --filter "The Matrix"

    # Use non-default Plex library names
    uv run unmonitarr.py --movie-library "Films" --show-library "Series"
"""

import argparse
import os
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

try:
    from plexapi.server import PlexServer
except ImportError:
    sys.exit("Missing dependency: pip install plexapi")


# --------------------------------------------------------------------------- #
# Config / CLI
# --------------------------------------------------------------------------- #

def _env_bool(name, default=False):
    """Parse a boolean flag's default from an env var (1/true/yes/on, case-insensitive)."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default=0):
    """Parse an integer flag's default from an env var."""
    val = os.environ.get(name)
    if val is None or not val.strip():
        return default
    return int(val)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plex-url", default=os.environ.get("PLEX_URL"))
    p.add_argument("--plex-token", default=os.environ.get("PLEX_TOKEN"))
    p.add_argument("--radarr-url", default=os.environ.get("RADARR_URL"))
    p.add_argument("--radarr-api-key", default=os.environ.get("RADARR_API_KEY"))
    p.add_argument("--sonarr-url", default=os.environ.get("SONARR_URL"))
    p.add_argument("--sonarr-api-key", default=os.environ.get("SONARR_API_KEY"))
    p.add_argument("--movie-library", default=os.environ.get("MOVIE_LIBRARY", "Movies"),
                    help="Plex movie library section name (env: MOVIE_LIBRARY)")
    p.add_argument("--show-library", default=os.environ.get("SHOW_LIBRARY", "TV Shows"),
                    help="Plex TV library section name (env: SHOW_LIBRARY)")
    p.add_argument("--skip-movies", action="store_true", default=_env_bool("SKIP_MOVIES"),
                    help="Don't process movies / Radarr (env: SKIP_MOVIES)")
    p.add_argument("--skip-shows", action="store_true", default=_env_bool("SKIP_SHOWS"),
                    help="Don't process TV episodes / Sonarr (env: SKIP_SHOWS)")
    p.add_argument("--apply", action="store_true", default=_env_bool("APPLY"),
                    help="Actually perform the changes. Without this flag, the script only "
                         "prints what it WOULD do (dry run). (env: APPLY)")
    p.add_argument("--hide-already-unmonitored", action="store_true",
                    default=_env_bool("HIDE_ALREADY_UNMONITORED"),
                    help="Don't print a line for items that are already unmonitored. Useful "
                         "when running this on a schedule alongside a tool like Maintainerr, "
                         "which may already unmonitor/clean up watched items itself -- without "
                         "this flag every run re-logs every item Maintainerr already handled. "
                         "(env: HIDE_ALREADY_UNMONITORED)")
    p.add_argument("--delete-movies", action="store_true", default=_env_bool("DELETE_MOVIES"),
                    help="Instead of unmonitoring, remove the watched movie from Radarr "
                         "entirely. Combine with --delete-files to also remove the files "
                         "from disk (default: Radarr entry is removed, files are kept). "
                         "(env: DELETE_MOVIES)")
    p.add_argument("--delete-episodes", action="store_true", default=_env_bool("DELETE_EPISODES"),
                    help="Instead of just unmonitoring, also delete the watched episode's "
                         "file from Sonarr (Sonarr has no concept of deleting a single episode "
                         "entry -- only its file -- so the episode remains listed but "
                         "unmonitored and file-less). (env: DELETE_EPISODES)")
    p.add_argument("--delete-files", action="store_true", default=_env_bool("DELETE_FILES"),
                    help="When used with --delete-movies, also delete the movie's files from "
                         "disk. Has no effect without --delete-movies. Episode file deletion "
                         "via --delete-episodes always removes the file (that's the point of "
                         "that flag) and is unaffected by this one. (env: DELETE_FILES)")
    p.add_argument("--unmonitor-after-days", type=int, default=_env_int("UNMONITOR_AFTER_DAYS", 0),
                    help="Only unmonitor a watched item once it's been watched at least this "
                         "many days (default: 0, i.e. immediately, same as before this flag "
                         "existed). (env: UNMONITOR_AFTER_DAYS)")
    p.add_argument("--delete-after-days", type=int, default=_env_int("DELETE_AFTER_DAYS", 0),
                    help="With --delete-movies/--delete-episodes, only delete once watched at "
                         "least this many days ago (default: 0, i.e. immediately). Has no effect "
                         "without --delete-movies/--delete-episodes. Applies even if the item "
                         "was already unmonitored by an earlier run. (env: DELETE_AFTER_DAYS)")
    p.add_argument("--filter", default=os.environ.get("FILTER"),
                    help="Only process movies/shows whose title contains this text "
                         "(case-insensitive). Mainly for testing against a single "
                         "movie/show. (env: FILTER)")
    args = p.parse_args()

    missing = []
    if not args.plex_url or not args.plex_token:
        missing.append("PLEX_URL / PLEX_TOKEN")
    if not args.skip_movies and (not args.radarr_url or not args.radarr_api_key):
        missing.append("RADARR_URL / RADARR_API_KEY (or pass --skip-movies)")
    if not args.skip_shows and (not args.sonarr_url or not args.sonarr_api_key):
        missing.append("SONARR_URL / SONARR_API_KEY (or pass --skip-shows)")
    if missing:
        p.error("Missing required configuration: " + "; ".join(missing))

    args.radarr_url = (args.radarr_url or "").rstrip("/")
    args.sonarr_url = (args.sonarr_url or "").rstrip("/")
    return args


# --------------------------------------------------------------------------- #
# Plex helpers
# --------------------------------------------------------------------------- #

def is_watched(item):
    """Robust watched-check across plexapi versions."""
    watched = getattr(item, "isWatched", None)
    if watched is not None:
        return bool(watched)
    return getattr(item, "viewCount", 0) > 0


def days_since_watched(item):
    """
    Days since `item.lastViewedAt`. Returns 0 (treated as "just watched") if
    Plex has no view timestamp for it despite it being watched, so an
    unknown watch date can't accidentally satisfy a >0 day threshold.
    """
    last_viewed = getattr(item, "lastViewedAt", None)
    if not last_viewed:
        return 0
    return max((datetime.now() - last_viewed).days, 0)


def extract_guid_ids(item):
    """
    Returns a dict like {'tmdb': '603', 'imdb': 'tt0133093', 'tvdb': '1396'}
    pulled from the modern `item.guids` list. Falls back to parsing the
    legacy single `item.guid` string if `guids` is empty (older agents).
    """
    ids = {}
    for g in getattr(item, "guids", []) or []:
        gid = getattr(g, "id", "") or ""
        if "://" in gid:
            source, _, value = gid.partition("://")
            ids[source.lower()] = value
    if not ids:
        legacy = getattr(item, "guid", "") or ""
        # e.g. com.plexapp.agents.themoviedb://603?lang=en
        #      com.plexapp.agents.thetvdb://71663?lang=en
        if "themoviedb://" in legacy:
            ids["tmdb"] = legacy.split("themoviedb://")[1].split("?")[0]
        elif "thetvdb://" in legacy:
            ids["tvdb"] = legacy.split("thetvdb://")[1].split("?")[0].split("/")[0]
        elif "imdb://" in legacy:
            ids["imdb"] = legacy.split("imdb://")[1].split("?")[0]
    return ids


# --------------------------------------------------------------------------- #
# Radarr
# --------------------------------------------------------------------------- #

def radarr_headers(api_key):
    return {"X-Api-Key": api_key}


def get_radarr_movies(radarr_url, api_key):
    r = requests.get(f"{radarr_url}/api/v3/movie", headers=radarr_headers(api_key), timeout=30)
    r.raise_for_status()
    return r.json()


def build_radarr_index(movies):
    index = {}
    for m in movies:
        if m.get("tmdbId"):
            index[("tmdb", str(m["tmdbId"]))] = m
        if m.get("imdbId"):
            index[("imdb", str(m["imdbId"]))] = m
    return index


def unmonitor_radarr_movie(radarr_url, api_key, movie, dry_run, hide_already, watched_days=None):
    watched_note = f" (watched {watched_days}d ago)" if watched_days is not None else ""
    if not movie.get("monitored", True):
        if not hide_already:
            print(f"    already unmonitored: {movie['title']} ({movie.get('year')}){watched_note}")
        return False

    action = "[DRY RUN] would unmonitor" if dry_run else "unmonitoring"
    print(f"    {action}: {movie['title']} ({movie.get('year')}){watched_note}")
    if dry_run:
        return True

    movie["monitored"] = False
    r = requests.put(
        f"{radarr_url}/api/v3/movie/{movie['id']}",
        json=movie,
        headers=radarr_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    return True


def delete_radarr_movie(radarr_url, api_key, movie, delete_files, dry_run, watched_days=None):
    watched_note = f" (watched {watched_days}d ago)" if watched_days is not None else ""
    action = "[DRY RUN] would delete" if dry_run else "deleting"
    files_note = " + files from disk" if delete_files else " (Radarr entry only, files kept)"
    print(f"    {action} from Radarr{files_note}: {movie['title']} ({movie.get('year')}){watched_note}")
    if dry_run:
        return True

    r = requests.delete(
        f"{radarr_url}/api/v3/movie/{movie['id']}",
        params={"deleteFiles": str(bool(delete_files)).lower(), "addImportExclusion": "false"},
        headers=radarr_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    return True


def process_movies(plex, args):
    print(f"\n=== Movies (Plex library: {args.movie_library!r}) ===")
    try:
        section = plex.library.section(args.movie_library)
    except Exception as e:
        print(f"  Could not open Plex movie library {args.movie_library!r}: {e}")
        return 0, 0

    radarr_movies = get_radarr_movies(args.radarr_url, args.radarr_api_key)
    radarr_index = build_radarr_index(radarr_movies)

    matched = 0
    changed = 0
    for plex_movie in section.all():
        if not is_watched(plex_movie):
            continue

        if args.filter and args.filter.lower() not in plex_movie.title.lower():
            continue

        ids = extract_guid_ids(plex_movie)
        movie = None
        if "tmdb" in ids:
            movie = radarr_index.get(("tmdb", ids["tmdb"]))
        if movie is None and "imdb" in ids:
            movie = radarr_index.get(("imdb", ids["imdb"]))

        if movie is None:
            print(f"  no Radarr match for watched movie: {plex_movie.title} ({plex_movie.year})")
            continue

        matched += 1
        days = days_since_watched(plex_movie)

        if args.delete_movies and days >= args.delete_after_days:
            # Delete regardless of current monitored state -- an item may
            # already have been unmonitored (by us or by something else)
            # on an earlier run, before it reached the delete threshold.
            if delete_radarr_movie(args.radarr_url, args.radarr_api_key, movie, args.delete_files,
                                    not args.apply, watched_days=days):
                changed += 1
        elif args.delete_movies:
            # Not old enough to delete yet -- unmonitor in the meantime so
            # it isn't re-searched/upgraded while it waits out the threshold.
            if days >= args.unmonitor_after_days:
                if unmonitor_radarr_movie(args.radarr_url, args.radarr_api_key, movie, not args.apply,
                                           hide_already=True, watched_days=days):
                    changed += 1
        else:
            if days < args.unmonitor_after_days:
                continue
            if unmonitor_radarr_movie(args.radarr_url, args.radarr_api_key, movie, not args.apply,
                                       args.hide_already_unmonitored, watched_days=days):
                changed += 1

    return matched, changed


# --------------------------------------------------------------------------- #
# Sonarr
# --------------------------------------------------------------------------- #

def sonarr_headers(api_key):
    return {"X-Api-Key": api_key}


def get_sonarr_series(sonarr_url, api_key):
    r = requests.get(f"{sonarr_url}/api/v3/series", headers=sonarr_headers(api_key), timeout=30)
    r.raise_for_status()
    return r.json()


def build_sonarr_series_index(series_list):
    return {str(s["tvdbId"]): s for s in series_list if s.get("tvdbId")}


def get_sonarr_episodes(sonarr_url, api_key, series_id):
    r = requests.get(
        f"{sonarr_url}/api/v3/episode",
        params={"seriesId": series_id},
        headers=sonarr_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def episode_label(show_title, episode):
    return f"{show_title} S{episode['seasonNumber']:02d}E{episode['episodeNumber']:02d}"


def unmonitor_sonarr_episode(sonarr_url, api_key, episode, show_title, dry_run, hide_already, watched_days=None):
    watched_note = f" (watched {watched_days}d ago)" if watched_days is not None else ""
    if not episode.get("monitored", True):
        if not hide_already:
            print(f"    already unmonitored: {episode_label(show_title, episode)}{watched_note}")
        return False

    action = "[DRY RUN] would unmonitor" if dry_run else "unmonitoring"
    print(f"    {action}: {episode_label(show_title, episode)}{watched_note}")
    if dry_run:
        return True

    episode["monitored"] = False
    r = requests.put(
        f"{sonarr_url}/api/v3/episode/{episode['id']}",
        json=episode,
        headers=sonarr_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    return True


def delete_sonarr_episode_file(sonarr_url, api_key, episode, show_title, dry_run, watched_days=None):
    """
    Sonarr has no API for removing a single episode entry (episodes are
    intrinsic to the series' metadata) -- the closest equivalent is
    deleting the episode's file. The episode is also unmonitored (by the
    caller) so Sonarr won't re-grab it afterwards.
    """
    watched_note = f" (watched {watched_days}d ago)" if watched_days is not None else ""
    file_id = episode.get("episodeFileId")
    if not file_id:
        print(f"    no file on disk to delete: {episode_label(show_title, episode)}{watched_note}")
        return False

    action = "[DRY RUN] would delete file for" if dry_run else "deleting file for"
    print(f"    {action}: {episode_label(show_title, episode)}{watched_note}")
    if dry_run:
        return True

    r = requests.delete(
        f"{sonarr_url}/api/v3/episodefile/{file_id}",
        headers=sonarr_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    return True


def process_shows(plex, args):
    print(f"\n=== TV episodes (Plex library: {args.show_library!r}) ===")
    try:
        section = plex.library.section(args.show_library)
    except Exception as e:
        print(f"  Could not open Plex show library {args.show_library!r}: {e}")
        return 0, 0

    series_list = get_sonarr_series(args.sonarr_url, args.sonarr_api_key)
    series_index = build_sonarr_series_index(series_list)

    # cache Sonarr episode lists per series so we don't re-fetch per episode
    episode_cache = {}

    matched = 0
    changed = 0
    for show in section.all():
        if args.filter and args.filter.lower() not in show.title.lower():
            continue

        show_ids = extract_guid_ids(show)
        tvdb_id = show_ids.get("tvdb")
        series = series_index.get(tvdb_id) if tvdb_id else None
        if series is None:
            continue  # show not in Sonarr

        for episode in show.episodes():
            if not is_watched(episode):
                continue

            series_id = series["id"]
            if series_id not in episode_cache:
                episode_cache[series_id] = get_sonarr_episodes(args.sonarr_url, args.sonarr_api_key, series_id)

            sonarr_episode = next(
                (
                    e for e in episode_cache[series_id]
                    if e.get("seasonNumber") == episode.parentIndex
                    and e.get("episodeNumber") == episode.index
                ),
                None,
            )

            if sonarr_episode is None:
                print(f"  no Sonarr match for watched episode: {show.title} "
                      f"S{episode.parentIndex:02d}E{episode.index:02d}")
                continue

            matched += 1
            days = days_since_watched(episode)
            did_something = False

            if args.delete_episodes and days >= args.delete_after_days:
                # Delete regardless of current monitored state -- the
                # episode may already have been unmonitored on an earlier
                # run, before it reached the delete threshold.
                if delete_sonarr_episode_file(args.sonarr_url, args.sonarr_api_key, sonarr_episode, show.title,
                                               not args.apply, watched_days=days):
                    did_something = True
                # always also unmonitor so Sonarr doesn't re-grab the file we just removed
                if unmonitor_sonarr_episode(args.sonarr_url, args.sonarr_api_key, sonarr_episode, show.title,
                                             not args.apply, hide_already=True, watched_days=days):
                    did_something = True
            elif args.delete_episodes:
                # Not old enough to delete yet -- unmonitor in the meantime.
                if days >= args.unmonitor_after_days:
                    if unmonitor_sonarr_episode(args.sonarr_url, args.sonarr_api_key, sonarr_episode, show.title,
                                                 not args.apply, hide_already=True, watched_days=days):
                        did_something = True
            else:
                if days >= args.unmonitor_after_days:
                    if unmonitor_sonarr_episode(args.sonarr_url, args.sonarr_api_key, sonarr_episode, show.title,
                                                 not args.apply, args.hide_already_unmonitored, watched_days=days):
                        did_something = True

            if did_something:
                changed += 1

    return matched, changed


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    args = parse_args()

    print(f"Mode: {'APPLY (will make changes)' if args.apply else 'DRY RUN (no changes will be made)'}")
    if args.delete_movies:
        print(f"Movies: DELETE from Radarr ({'with' if args.delete_files else 'without'} files)"
              f" after {args.delete_after_days}d watched")
    if args.delete_episodes:
        print(f"Episodes: DELETE file from Sonarr + unmonitor after {args.delete_after_days}d watched")
    if args.unmonitor_after_days:
        print(f"Unmonitor threshold: {args.unmonitor_after_days}d watched")
    if args.filter:
        print(f"Filter: only titles containing {args.filter!r}")

    try:
        plex = PlexServer(args.plex_url, args.plex_token)
    except Exception as e:
        sys.exit(f"Could not connect to Plex at {args.plex_url}: {e}")

    total_matched = 0
    total_changed = 0

    if not args.skip_movies:
        m, c = process_movies(plex, args)
        total_matched += m
        total_changed += c

    if not args.skip_shows:
        m, c = process_shows(plex, args)
        total_matched += m
        total_changed += c

    print("\n=== Summary ===")
    print(f"Watched items matched in Radarr/Sonarr: {total_matched}")
    if args.apply:
        print(f"Items changed: {total_changed}")
    else:
        print(f"Items that WOULD be changed: {total_changed}")
        print("Re-run with --apply to make these changes.")


if __name__ == "__main__":
    main()
