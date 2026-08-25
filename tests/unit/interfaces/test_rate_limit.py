"""Limiteur de débit à fenêtre fixe (anti-bruteforce du login)."""

from fastapi import Request

from interfaces.api.rate_limit import FixedWindowRateLimiter, _client_key


def _request(client_host: str | None, **headers: str) -> Request:
    """Requête minimale portant une adresse de connexion et des en-têtes."""
    return Request(
        {
            "type": "http",
            "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()],
            "client": (client_host, 51234) if client_host else None,
        }
    )


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


class TestClientKey:
    """La clé du limiteur suit l'adresse de connexion, jamais un en-tête fourni par l'appelant."""

    def test_forged_forwarded_header_does_not_change_the_key(self):
        forged = _request("10.0.0.7", x_forwarded_for="1.2.3.4, 5.6.7.8")
        assert _client_key(forged) == "10.0.0.7"
        assert _client_key(forged) == _client_key(_request("10.0.0.7"))

    def test_missing_client_falls_back_to_a_stable_key(self):
        assert _client_key(_request(None)) == "unknown"
