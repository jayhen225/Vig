"""Capture a raw snapshot of NFL player-prop odds from The Odds API.

Line-movement history cannot be backfilled -- it only exists if we capture it
going forward. This script lists the current week's NFL events, then pulls
player-prop odds for each event and writes the raw JSON to disk, timestamped
so snapshots never overwrite each other.

The API key is read from the ODDS_API_KEY environment variable (a GitHub
Actions secret in CI, a shell / .env variable locally) -- never hardcoded, so
this file is safe to commit to a public repo.

Two-step API shape:
  1. list events (games) for the sport   -> gives each event an id
  2. for each event id, pull its props    -> one request per event
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
REGIONS = "us"
ODDS_FORMAT = "american"

# Player-prop markets to capture. Each market requested costs API credits *per
# event*, so trim this list if you need to conserve quota.
MARKETS = [
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
]

# Only snapshot games kicking off within this many days. Books post player props
# close to game time, so pulling every future game on the schedule just wastes
# API credits (and time) on events that have no props yet.
SNAPSHOT_WINDOW_DAYS = 7

# Snapshots live under parlay/data/odds_raw/, separate from the nflverse parquet
# files in parlay/data/raw/. Path is anchored to this file, not the cwd.
SNAPSHOT_ROOT = Path(__file__).parent.parent / "data" / "odds_raw"


def build_url(path, **params):
    """Build a full API URL with query parameters."""
    return f"{API_BASE}{path}?{urlencode(params)}"


def upcoming_events(events, now, window_days=SNAPSHOT_WINDOW_DAYS):
    """Keep only events kicking off between now and now + window_days."""
    cutoff = now + timedelta(days=window_days)
    kept = []
    for event in events:
        commence = event.get("commence_time")
        if not commence:
            continue
        start = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        if now <= start <= cutoff:
            kept.append(event)
    return kept


def get_json(url):
    """GET a URL; return (parsed_json, response_headers)."""
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.headers


def main():
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        sys.exit("ODDS_API_KEY is not set. Add it as an env var / GitHub secret.")

    now = datetime.now(timezone.utc)

    # Step 1: list events, then keep only games within the snapshot window.
    events_url = build_url(f"/sports/{SPORT}/events", apiKey=api_key)
    try:
        events, headers = get_json(events_url)
    except urllib.error.HTTPError as e:
        sys.exit(f"Failed to list events: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Failed to list events: {e.reason}")

    events = upcoming_events(events, now)
    print(
        f"{len(events)} games within {SNAPSHOT_WINDOW_DAYS} days. "
        f"Credits remaining: {headers.get('x-requests-remaining')}"
    )
    if not events:
        print("No upcoming games in window -- nothing to snapshot.")
        return

    # One folder per run, named by UTC timestamp, so nothing is overwritten.
    out_dir = SNAPSHOT_ROOT / now.strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "events.json").write_text(json.dumps(events, indent=2))
    print(f"Writing snapshot to {out_dir}")

    # Step 2: pull player props per event. Wrap each call so one failure doesn't
    # lose the rest of the week's snapshot; skip events with no props posted yet
    # so we don't commit empty files.
    saved, empty, failed = 0, 0, 0
    for event in events:
        event_id = event["id"]
        matchup = f"{event.get('away_team')} @ {event.get('home_team')}"
        url = build_url(
            f"/sports/{SPORT}/events/{event_id}/odds",
            apiKey=api_key,
            regions=REGIONS,
            markets=",".join(MARKETS),
            oddsFormat=ODDS_FORMAT,
        )
        try:
            props, headers = get_json(url)
        except urllib.error.HTTPError as e:
            print(f"  {matchup}: HTTP {e.code} {e.reason} -- skipping")
            failed += 1
            continue
        except urllib.error.URLError as e:
            print(f"  {matchup}: {e.reason} -- skipping")
            failed += 1
            continue

        if not props.get("bookmakers"):
            print(f"  {matchup}: no props posted yet -- skipping")
            empty += 1
            continue

        (out_dir / f"{event_id}.json").write_text(json.dumps(props, indent=2))
        saved += 1
        print(f"  {matchup} -> saved (credits left: {headers.get('x-requests-remaining')})")

    print(f"Done. {saved} saved, {empty} empty, {failed} failed.")
    # Fail loudly only if every request errored -- an all-empty result is normal
    # early in the week before books post props.
    if failed and saved == 0:
        sys.exit("All prop requests failed -- check markets / quota.")


if __name__ == "__main__":
    main()
