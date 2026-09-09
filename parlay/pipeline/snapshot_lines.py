"""Capture a raw snapshot of NFL spread/moneyline/total odds from The Odds API.

Cheaper sibling of snapshot_odds.py: that script pulls 6 player-prop markets
per event (6 credits/event). This one pulls only the 3 core game-line markets
(h2h, spreads, totals), which The Odds API bundles into a SINGLE credit per
event/region regardless of how many of those three markets you request --
so a full week's slate costs roughly 1 credit per game instead of 6.

That's what makes this script viable for a sustained weekly cron on the free
tier (500 credits/month), where the player-prop script is only run manually
on demand.

Line-movement history cannot be backfilled -- it only exists if we capture it
going forward. This script lists the current week's NFL events, then pulls
game-line odds for each event and writes the raw JSON to disk, timestamped
so snapshots never overwrite each other.

The API key is read from the ODDS_API_KEY environment variable (a GitHub
Actions secret in CI, a shell / .env variable locally) -- never hardcoded, so
this file is safe to commit to a public repo.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from dotenv import load_dotenv
load_dotenv()

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
REGIONS = "us"
ODDS_FORMAT = "american"

# Core game-line markets. Unlike player props, these three are bundled into
# one credit per event/region when requested together -- confirm current
# credit cost against your account's usage after a manual run, since pricing
# details can change.
MARKETS = [
    "h2h",       # moneyline
    "spreads",
    "totals",
]

# Only snapshot games kicking off within this many days.
SNAPSHOT_WINDOW_DAYS = 7

# Snapshots live under parlay/data/odds_raw_lines/, kept separate from the
# player-prop snapshots in parlay/data/odds_raw/ so the two capture
# cadences (weekly cheap vs. on-demand expensive) don't mix in one folder.
SNAPSHOT_ROOT = Path(__file__).parent.parent / "data" / "odds_raw_lines"


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

    # Step 2: pull game-line odds per event.
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
            lines, headers = get_json(url)
        except urllib.error.HTTPError as e:
            print(f"  {matchup}: HTTP {e.code} {e.reason} -- skipping")
            failed += 1
            continue
        except urllib.error.URLError as e:
            print(f"  {matchup}: {e.reason} -- skipping")
            failed += 1
            continue

        if not lines.get("bookmakers"):
            print(f"  {matchup}: no lines posted yet -- skipping")
            empty += 1
            continue

        (out_dir / f"{event_id}.json").write_text(json.dumps(lines, indent=2))
        saved += 1
        print(f"  {matchup} -> saved (credits left: {headers.get('x-requests-remaining')})")

    print(f"Done. {saved} saved, {empty} empty, {failed} failed.")
    if failed and saved == 0:
        sys.exit("All line requests failed -- check markets / quota.")


if __name__ == "__main__":
    main()