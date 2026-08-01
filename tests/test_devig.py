import json
import math
from pathlib import Path

import pytest

from parlay.core.devig import (
    american_to_prob,
    consensus_prob,
    devig,
    expected_value,
    is_positive_ev,
    prob_to_american,
)
from pipeline.devig_odds import devig_rows, flatten_event

FIXTURES = Path(__file__).parent / "fixtures"


def test_american_to_prob():
    assert american_to_prob(150) == 0.4
    assert math.isclose(american_to_prob(-200), 2 / 3)
    assert american_to_prob(100) == 0.5


def test_prob_to_american_roundtrip():
    for price in (150, -200, 100, -110, 250):
        assert prob_to_american(american_to_prob(price)) == price


def test_prob_to_american_rejects_out_of_range():
    for bad in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError):
            prob_to_american(bad)


def test_devig_multiplicative_sums_to_one():
    fair = devig([american_to_prob(-115), american_to_prob(-105)])
    assert math.isclose(sum(fair), 1.0)
    # The side with the higher implied prob keeps the higher fair prob.
    assert fair[0] > fair[1]


def test_devig_unknown_method():
    with pytest.raises(ValueError):
        devig([0.5, 0.5], method="nope")


def test_consensus_prob():
    assert consensus_prob([0.5, 0.4, 0.6]) == 0.5
    assert consensus_prob([0.4, 0.6], method="mean") == 0.5
    assert consensus_prob([]) is None
    assert consensus_prob([None, None]) is None


def test_expected_value_sign():
    # +150 implies .40 but true prob is .45 -> generous, +EV.
    assert expected_value(150, 0.45) > 0
    assert is_positive_ev(150, 0.45)
    # -200 implies .667 but true prob is .60 -> stingy, -EV.
    assert expected_value(-200, 0.60) < 0
    assert not is_positive_ev(-200, 0.60)


def test_pipeline_flatten_devig_and_consensus():
    event = json.loads((FIXTURES / "sample_event.json").read_text())
    rows = devig_rows(flatten_event(event, "20260909T230000Z"))

    def find(**kw):
        return next(r for r in rows if all(r[k] == v for k, v in kw.items()))

    # A complete 2-sided market de-vigs to fair probs that sum to 1.0 per book.
    over = find(bookmaker="draftkings", market="player_pass_yds", side="Over")
    under = find(bookmaker="draftkings", market="player_pass_yds", side="Under")
    assert math.isclose(over["book_fair_prob"] + under["book_fair_prob"], 1.0)

    # Consensus spans both books; probability is well-formed.
    assert over["n_books"] == 2
    assert 0 < over["consensus_fair_prob"] < 1
    assert over["ev_per_dollar"] is not None
    assert over["is_positive_ev"] in (True, False)

    # A one-sided market (anytime TD, no "No") is flagged, never crashes.
    td = find(market="player_anytime_td")
    assert td["book_fair_prob"] is None
    assert td["consensus_fair_prob"] is None
    assert td["is_positive_ev"] is None
