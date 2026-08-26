from datetime import datetime, timedelta, timezone

from parlay.pipeline.snapshot_odds import upcoming_events


def _event(days_from_now, now):
    commence = (now + timedelta(days=days_from_now)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": "x", "commence_time": commence}


def test_upcoming_events_keeps_only_games_in_window():
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    events = [
        _event(1, now),  # tomorrow -> keep
        _event(6, now),  # in 6 days -> keep
        _event(30, now),  # far future -> drop
        _event(-1, now),  # already started -> drop
        {"id": "no_time"},  # missing commence_time -> drop
    ]
    kept = upcoming_events(events, now, window_days=7)
    assert len(kept) == 2


def test_upcoming_events_empty_when_offseason():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    events = [_event(45, now), _event(90, now)]  # all weeks away
    assert upcoming_events(events, now, window_days=7) == []
