"""Limiteur de débit à fenêtre fixe (anti-bruteforce du login)."""

import logging

from fastapi import Request

from interfaces.api.rate_limit import (
    FixedWindowRateLimiter,
    _client_key,
    reset_rate_limiters,
)


def _request(client_host: str | None, port: int = 51234, **headers: str) -> Request:
    """Requête minimale portant une adresse de connexion, un port et des en-têtes.

    Le port vaut 0 quand le serveur ASGI a réécrit l'adresse depuis `X-Forwarded-For` : il perd l'information à cette occasion, et c'est à cela qu'on reconnaît un en-tête pris en compte.
    """
    return Request(
        {
            "type": "http",
            "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()],
            "client": (client_host, port) if client_host else None,
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

    def test_expired_counters_are_purged_before_inserting(self):
        clock = _Clock()
        limiter = FixedWindowRateLimiter(1, 60, max_keys=2, clock=clock)
        limiter.allow("a")
        limiter.allow("b")
        # Fenêtres écoulées : la clé suivante déclenche la purge avant insertion.
        clock.t = 60
        limiter.allow("c")
        assert limiter._hits.keys() == {"c"}


class TestMemoryBound:
    """Non-régression : le plafond de compteurs suivis ne bornait rien tant qu'aucune fenêtre n'était écoulée.

    La purge ne retirait que les fenêtres écoulées, et le compteur du nouvel arrivant était enregistré dans tous les cas : sous un flot d'adresses distinctes tombant dans une même fenêtre, la table grossissait sans limite — ce que le code annonçait impossible.
    """

    def test_a_flood_of_fresh_counters_stays_under_the_cap(self):
        limiter = FixedWindowRateLimiter(1, 60, max_keys=4, clock=_Clock())
        for i in range(1000):
            limiter.allow(f"adresse-{i}")
        assert len(limiter._hits) == 4

    def test_the_oldest_window_is_the_one_dropped(self):
        """Celle qui allait expirer la première : son oubli coûte le moins."""
        clock = _Clock()
        limiter = FixedWindowRateLimiter(5, 60, max_keys=3, clock=clock)
        for nom in ("a", "b", "c"):
            limiter.allow(nom)
            clock.t += 1
        limiter.allow("d")
        assert list(limiter._hits) == ["b", "c", "d"]

    def test_counting_again_does_not_change_a_rank(self):
        """Recompter dans une fenêtre en cours n'en déplace pas le début : `a` reste le plus ancien."""
        clock = _Clock()
        limiter = FixedWindowRateLimiter(5, 60, max_keys=3, clock=clock)
        limiter.allow("a")
        clock.t += 1
        limiter.allow("b")
        clock.t += 1
        limiter.allow("a")
        limiter.allow("c")
        limiter.allow("d")
        assert list(limiter._hits) == ["b", "c", "d"]

    def test_a_restarted_window_goes_to_the_back(self):
        clock = _Clock()
        limiter = FixedWindowRateLimiter(5, 60, max_keys=3, clock=clock)
        limiter.allow("a")
        clock.t += 1
        limiter.allow("b")
        clock.t += 1
        limiter.allow("c")
        clock.t = 100  # la fenêtre de `a` est écoulée, elle repart
        limiter.allow("a")
        assert list(limiter._hits) == ["b", "c", "a"]

    def test_an_evicted_client_gets_its_attempts_back(self):
        """Contrepartie assumée du plafond : sous flot, un client suivi peut perdre son compteur avant la fin de sa fenêtre."""
        limiter = FixedWindowRateLimiter(1, 60, max_keys=2, clock=_Clock())
        assert limiter.allow("victime") is True
        assert limiter.allow("victime") is False
        limiter.allow("flot-1")
        limiter.allow("flot-2")
        assert limiter.allow("victime") is True

    def test_a_tracked_client_does_not_evict_anyone(self):
        """Une adresse déjà suivie n'ajoute pas de compteur : rien à libérer pour l'accueillir."""
        limiter = FixedWindowRateLimiter(5, 60, max_keys=2, clock=_Clock())
        limiter.allow("a")
        limiter.allow("b")
        limiter.allow("a")
        assert list(limiter._hits) == ["a", "b"]


class TestClientKey:
    """La clé du limiteur suit l'adresse de connexion, jamais un en-tête fourni par l'appelant."""

    def test_forged_forwarded_header_does_not_change_the_key(self):
        forged = _request("10.0.0.7", x_forwarded_for="1.2.3.4, 5.6.7.8")
        assert _client_key(forged) == "10.0.0.7"
        assert _client_key(forged) == _client_key(_request("10.0.0.7"))

    def test_missing_client_falls_back_to_a_stable_key(self):
        assert _client_key(_request(None)) == "unknown"


class TestProxyHeaderIgnoredWarning:
    """Un en-tête de proxy écarté par le serveur ASGI se signale au journal.

    Le plafond de tentatives compte alors tous les clients dans un même seau, ce qui laisse un tiers interdire la connexion d'administration à tout le monde. Le signalement nomme le pair, valeur à porter dans `FORWARDED_ALLOW_IPS`.
    """

    def setup_method(self):
        reset_rate_limiters()

    def test_signale_un_pair_non_declare(self, caplog):
        with caplog.at_level(logging.WARNING):
            _client_key(_request("172.17.0.1", x_forwarded_for="203.0.113.9"))
        assert "proxy_headers_ignored" in caplog.text
        assert "172.17.0.1" in caplog.records[0].detail

    def test_ne_signale_qu_une_fois_par_pair(self, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                _client_key(_request("172.17.0.1", x_forwarded_for="203.0.113.9"))
        assert len(caplog.records) == 1

    def test_silence_quand_le_serveur_a_pris_l_en_tete(self, caplog):
        # Port nul : le serveur a réécrit l'adresse, le réglage est donc correct.
        with caplog.at_level(logging.WARNING):
            _client_key(_request("203.0.113.9", port=0, x_forwarded_for="203.0.113.9"))
        assert caplog.records == []

    def test_silence_sans_en_tete_de_proxy(self, caplog):
        with caplog.at_level(logging.WARNING):
            _client_key(_request("172.17.0.1"))
        assert caplog.records == []
