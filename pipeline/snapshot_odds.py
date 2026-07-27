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
from datetime import datetime, timezone
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

# Snapshots live under data/odds_raw/, separate from the nflverse parquet files
# in data/raw/. Path is anchored to this file, not the working directory.
SNAPSHOT_ROOT = Path(__file__).parent.parent / "data" / "odds_raw"


def build_url(path, **params):
    """Build a full API URL with query parameters."""
    return f"{API_BASE}{path}?{urlencode(params)}"


def get_json(url):
    """GET a URL; return (parsed_json, response_headers)."""
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.headers


def main():
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        sys.exit("ODDS_API_KEY is not set. Add it as an env var / GitHub secret.")

    # One folder per run, named by UTC timestamp, so nothing is overwritten.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = SNAPSHOT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing snapshot to {out_dir}")

    # Step 1: list this week's events. Need each event id to pull its props.
    events_url = build_url(f"/sports/{SPORT}/events", apiKey=api_key)
    try:
        events, headers = get_json(events_url)
    except urllib.error.HTTPError as e:
        sys.exit(f"Failed to list events: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Failed to list events: {e.reason}")

    (out_dir / "events.json").write_text(json.dumps(events, indent=2))
    print(f"{len(events)} events. Credits remaining: {headers.get('x-requests-remaining')}")

    # Step 2: for each event, pull player props. Wrap each call so one failure
    # doesn't lose the rest of the week's snapshot.
    saved, failed = 0, 0
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

        (out_dir / f"{event_id}.json").write_text(json.dumps(props, indent=2))
        saved += 1
        print(f"  {matchup} -> saved (credits left: {headers.get('x-requests-remaining')})")

    print(f"Done. {saved} saved, {failed} failed.")
    # A run that lists games but captures zero props means something is wrong
    # (bad markets, exhausted quota) -- fail loudly rather than commit an empty snapshot.
    if events and saved == 0:
        sys.exit("No event props were captured -- check markets / quota.")


if __name__ == "__main__":
    main()
