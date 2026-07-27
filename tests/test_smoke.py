"""Smoke tests.

Minimal placeholder so the suite collects at least one test -- pytest exits
with an error ("no tests collected") on an empty suite, which fails CI.
Replace/expand these as real functionality lands.
"""


def test_parlay_package_imports():
    import parlay

    assert parlay is not None
