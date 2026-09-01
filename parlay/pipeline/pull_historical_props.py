"""Pull historical NFL player prop odds from The Odds API (2025 season).

Strategy:
  1. Get all 2025 NFL event IDs (free endpoint, no credit cost)
  2. For each event, pull closing-line prop odds for:
     - player_pass_yds (QB passing yards)
     - player_rush_yds (RB rushing yards)
     - player_reception_yds (WR/TE receiving yards)
  3. Save each event's odds as JSON, matching the format
     the existing devig pipeline expects

Credit budget: 270 games × 3 markets × 10 credits = ~8,100 of 20,000

Usage:
  uv run python pipeline/pull_historical_props.py
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

# Load API key from .env file
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    raise ValueError("ODDS_API_KEY not found. Add it to your .env file: ODDS_API_KEY=your_key_here")

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# Where to save the pulled data
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "odds_historical"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Prop markets to pull (the three that match your models)
PROP_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
]

# 2025 NFL regular season: Sept 4, 2025 through Jan 4, 2026
# Pull closing odds by requesting a timestamp near each game's start
SEASON_START = datetime(2025, 9, 4)
SEASON_END = datetime(2026, 1, 10)  # include wild card round


def get_historical_events(date_str):
    """Get NFL events for a specific date snapshot.
    
    This endpoint returns event IDs and commence times.
    Cost: 0 credits (events endpoint is free).
    """
    url = f"{BASE_URL}/historical/sports/{SPORT}/events"
    params = {
        "apiKey": API_KEY,
        "date": date_str,
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def get_historical_event_odds(event_id, date_str, markets):
    """Get historical odds for a specific event at a specific timestamp.
    
    Cost: 10 credits per region per market.
    With 3 markets and 1 region (us): 30 credits per event.
    """
    url = f"{BASE_URL}/historical/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "date": date_str,
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params)

    if resp.status_code == 422:
        # Event not found or no odds available for this timestamp
        return None
    
    resp.raise_for_status()
    
    # Track remaining credits from response headers
    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    print(f"    Credits used: {used}, remaining: {remaining}")
    
    return resp.json()


def main():
    print(f"Pulling historical NFL prop odds for 2025 season")
    print(f"Markets: {PROP_MARKETS}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    # ── Step 1: Get all events across the season ──
    # Query weekly snapshots to find all game IDs
    print("Step 1: Discovering 2025 NFL events...")
    
    all_events = {}  # event_id -> event_info
    
    current = SEASON_START
    while current <= SEASON_END:
        date_str = current.strftime("%Y-%m-%dT12:00:00Z")
        print(f"  Checking {date_str[:10]}...", end=" ")
        
        try:
            result = get_historical_events(date_str)
            events = result.get("data", [])
            new_count = 0
            for event in events:
                if event["id"] not in all_events:
                    all_events[event["id"]] = event
                    new_count += 1
            print(f"{len(events)} events found, {new_count} new")
        except Exception as e:
            print(f"Error: {e}")
        
        current += timedelta(days=7)
        time.sleep(0.5)  # be nice to the API

    print(f"\nTotal unique events discovered: {len(all_events)}")

    # ── Step 2: Pull prop odds for each event ──
    print(f"\nStep 2: Pulling prop odds for {len(all_events)} events...")
    print(f"Estimated credit cost: {len(all_events) * 30} credits")
    print()

    success = 0
    skipped = 0
    errors = 0

    for i, (event_id, event_info) in enumerate(sorted(all_events.items(), key=lambda x: x[1].get("commence_time", ""))):
        # Check if already pulled
        out_path = OUTPUT_DIR / f"{event_id}.json"
        if out_path.exists():
            skipped += 1
            continue

        commence = event_info.get("commence_time", "")
        home = event_info.get("home_team", "?")
        away = event_info.get("away_team", "?")

        # Request odds from ~2 hours before game time (closing line approximation)
        try:
            commence_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            closing_dt = commence_dt - timedelta(hours=2)
            date_str = closing_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, AttributeError):
            date_str = commence

        print(f"  [{i+1}/{len(all_events)}] {away} @ {home} ({commence[:10]})")

        try:
            odds_data = get_historical_event_odds(event_id, date_str, PROP_MARKETS)
            
            if odds_data is None:
                print(f"    No odds available")
                skipped += 1
                continue

            # Save the full response
            save_data = {
                "event_id": event_id,
                "event_info": event_info,
                "odds_timestamp": date_str,
                "odds_data": odds_data,
            }
            out_path.write_text(json.dumps(save_data, indent=2))
            success += 1
            print(f"    Saved")

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"    Rate limited — waiting 60s...")
                time.sleep(60)
                errors += 1
            elif e.response.status_code == 402:
                print(f"    Out of credits! Stopping.")
                break
            else:
                print(f"    HTTP error: {e}")
                errors += 1
        except Exception as e:
            print(f"    Error: {e}")
            errors += 1

        # Rate limiting: ~1 request per second
        time.sleep(1)

    print(f"\n── Summary ──")
    print(f"Events pulled:  {success}")
    print(f"Skipped (already saved or no odds): {skipped}")
    print(f"Errors: {errors}")
    print(f"Files saved to: {OUTPUT_DIR}")

    # ── Step 3: Quick inventory of what we got ──
    files = list(OUTPUT_DIR.glob("*.json"))
    print(f"\nTotal JSON files in {OUTPUT_DIR}: {len(files)}")

    if files:
        # Check one file to confirm format
        sample = json.loads(files[0].read_text())
        event = sample.get("event_info", {})
        odds = sample.get("odds_data", {})
        print(f"Sample: {event.get('away_team', '?')} @ {event.get('home_team', '?')}")
        
        # Count bookmakers and markets in the sample
        data = odds.get("data", odds)  # handle different response structures
        if isinstance(data, dict):
            bookmakers = data.get("bookmakers", [])
            print(f"  Bookmakers: {len(bookmakers)}")
            if bookmakers:
                markets = bookmakers[0].get("markets", [])
                print(f"  Markets from {bookmakers[0].get('key', '?')}: {[m.get('key') for m in markets]}")


if __name__ == "__main__":
    main()