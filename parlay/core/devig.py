"""Pricing primitives: odds <-> probability, de-vigging, consensus, expected value.

Pure functions only (no IO), so they're cheap to unit-test and reuse. The
de-vig method is chosen via a small registry (``DEVIG_METHODS``) so more
sophisticated methods (Shin's, power) can be added later behind the same
``devig(...)`` interface without touching callers.

Key relationships:
  * Implied probability from American price: ``+O -> 100/(O+100)``, ``-O -> O/(O+100)``.
  * De-vig = strip the book's margin so a market's outcome probabilities sum to 1.
  * Expected value uses the book's *vigged* price against a *fair* probability --
    you bet at the price offered; the edge is whether that payout beats the truth.
"""

import statistics

__all__ = [
    "DEVIG_METHODS",
    "american_to_prob",
    "consensus_prob",
    "decimal_profit",
    "devig",
    "expected_value",
    "is_positive_ev",
    "prob_to_american",
]


def american_to_prob(price):
    """Implied probability of a moneyline-style American price."""
    if price > 0:
        return 100 / (price + 100)
    return -price / (-price + 100)


def prob_to_american(prob):
    """Fair American price for a probability in the open interval (0, 1)."""
    if not 0 < prob < 1:
        raise ValueError(f"prob must be in (0, 1), got {prob}")
    if prob > 0.5:
        return round(-100 * prob / (1 - prob))
    return round(100 * (1 - prob) / prob)


def decimal_profit(price):
    """Profit per $1 staked at an American price (decimal odds minus 1)."""
    if price > 0:
        return price / 100
    return 100 / -price


def _multiplicative(probs):
    """Proportional (multiplicative) normalization -- the standard de-vig."""
    total = sum(probs)
    if total <= 0:
        raise ValueError("implied probabilities must sum to a positive number")
    return [p / total for p in probs]


# Registry of de-vig methods. Add e.g. "shin" / "power" here later; callers keep
# using devig(probs, method=...).
DEVIG_METHODS = {
    "multiplicative": _multiplicative,
}


def devig(probs, method="multiplicative"):
    """Remove the vig from a market's implied probabilities so they sum to 1.

    ``probs`` are the raw implied probabilities of every outcome in one market
    (e.g. the Over and Under of a single player/line at a single book).
    """
    if method not in DEVIG_METHODS:
        raise ValueError(f"unknown de-vig method {method!r}; choose from {sorted(DEVIG_METHODS)}")
    return DEVIG_METHODS[method](probs)


def consensus_prob(probs, method="median"):
    """Combine one outcome's fair probabilities across books into a consensus.

    Median is the default (robust to a single stray book); mean is available.
    Returns None if there are no probabilities to combine.
    """
    values = [p for p in probs if p is not None]
    if not values:
        return None
    if method == "median":
        return statistics.median(values)
    if method == "mean":
        return statistics.fmean(values)
    raise ValueError(f"unknown consensus method {method!r}; choose 'median' or 'mean'")


def expected_value(price, fair_prob):
    """Expected profit per $1 staked at ``price`` given the true ``fair_prob``.

    Positive means the offered price pays more than the fair probability warrants.
    """
    return fair_prob * decimal_profit(price) - (1 - fair_prob)


def is_positive_ev(price, fair_prob, threshold=0.0):
    """True when expected value per $1 exceeds ``threshold`` (default break-even)."""
    return expected_value(price, fair_prob) > threshold
