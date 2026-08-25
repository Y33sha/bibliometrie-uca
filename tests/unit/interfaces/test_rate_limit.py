"""Limiteur de débit à fenêtre fixe (anti-bruteforce du login)."""

from interfaces.api.rate_limit import FixedWindowRateLimiter


class _Clock:
    """Horloge pilotée pour des fenêtres déterministes."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class TestFixedWindowRateLimiter:
    def test_allows_up_to_max_then_blocks(self):
        limiter = FixedWindowRateLimiter(3, 60, clock=_Clock())
        assert [limiter.allow("ip") for _ in range(3)] == [True, True, True]
        assert limiter.allow("ip") is False

    def test_window_resets_after_expiry(self):
        clock = _Clock()
        limiter = FixedWindowRateLimiter(2, 60, clock=clock)
        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is False
        clock.t = 60
        assert limiter.allow("ip") is True

    def test_keys_are_independent(self):
        limiter = FixedWindowRateLimiter(1, 60, clock=_Clock())
        assert limiter.allow("a") is True
        assert limiter.allow("a") is False
        assert limiter.allow("b") is True

    def test_reset_clears_all_counters(self):
        limiter = FixedWindowRateLimiter(1, 60, clock=_Clock())
        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is False
        limiter.reset()
        assert limiter.allow("ip") is True

    def test_prune_bounds_tracked_keys(self):
        clock = _Clock()
        limiter = FixedWindowRateLimiter(1, 60, max_keys=2, clock=clock)
        limiter.allow("a")
        limiter.allow("b")
        # Fenêtres expirées : la clé suivante déclenche l'élagage avant insertion.
        clock.t = 60
        limiter.allow("c")
        assert limiter._hits.keys() == {"c"}
