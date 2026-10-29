"""Limiteur de débit à fenêtre fixe : compteurs, clé du client et signalement d'un en-tête de proxy ignoré."""

import logging

from fastapi import Request

from interfaces.api import rate_limit
from interfaces.api.rate_limit import (
    FixedWindowRateLimiter,
    _client_key,
    reset_rate_limiters,
)


def _request(client_host: str | None, port: int = 51234, **headers: str) -> Request:
    """Requête minimale avec une adresse de connexion, un port et des en-têtes.

    Le port vaut 0 quand le serveur ASGI a réécrit l'adresse depuis `X-Forwarded-For`. Un port nul signale donc un en-tête pris en compte.
    """
    return Request(
        {
            "type": "http",
            "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()],
            "client": (client_host, port) if client_host else None,
        }
    )


class _Clock:
    """Horloge pilotée par le test, pour des fenêtres déterministes."""

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
    """Le nombre de compteurs suivis reste sous le plafond, même sans fenêtre écoulée.

    Sous un flot d'adresses distinctes dans une même fenêtre, la purge des fenêtres écoulées reste sans effet : le compteur de la fenêtre la plus ancienne est alors retiré.
    """

    def test_a_flood_of_fresh_counters_stays_under_the_cap(self):
        limiter = FixedWindowRateLimiter(1, 60, max_keys=4, clock=_Clock())
        for i in range(1000):
            limiter.allow(f"adresse-{i}")
        assert len(limiter._hits) == 4

    def test_the_oldest_window_is_the_one_dropped(self):
        """Le compteur retiré est celui de la fenêtre la plus ancienne, qui expire la première."""
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
        """Contrepartie du plafond : sous un flot d'adresses, un client suivi peut perdre son compteur avant la fin de sa fenêtre."""
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
    """Un en-tête de proxy ignoré par le serveur ASGI est signalé au journal.

    Le plafond de tentatives compte alors tous les clients ensemble : un tiers peut bloquer la connexion d'administration pour tout le monde. Le signalement nomme le pair, valeur à ajouter à `FORWARDED_ALLOW_IPS`.
    """

    def setup_method(self):
        reset_rate_limiters()

    def test_signale_un_pair_non_declare(self, caplog):
        with caplog.at_level(logging.WARNING):
            _client_key(_request("172.17.0.1", x_forwarded_for="203.0.113.9"))
        assert "proxy_headers_ignored" in caplog.text
        assert "172.17.0.1" in caplog.records[0].detail

    def test_ne_signale_qu_une_fois_par_pair_dans_l_intervalle(self, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                _client_key(_request("172.17.0.1", x_forwarded_for="203.0.113.9"))
        assert len(caplog.records) == 1

    def test_se_repete_passe_l_intervalle(self, caplog, monkeypatch):
        """Passé l'intervalle, le signalement se répète : il reste visible dans le journal tant que le réglage est faux."""
        monkeypatch.setattr(rate_limit, "_WARN_INTERVAL_SECONDS", 0.0)
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                _client_key(_request("172.17.0.1", x_forwarded_for="203.0.113.9"))
        assert len(caplog.records) == 3

    def test_signale_chaque_pair_distinct(self, caplog):
        with caplog.at_level(logging.WARNING):
            _client_key(_request("172.17.0.1", x_forwarded_for="203.0.113.9"))
            _client_key(_request("172.18.0.1", x_forwarded_for="203.0.113.9"))
        assert {r.peer for r in caplog.records} == {"172.17.0.1", "172.18.0.1"}

    def test_la_table_des_pairs_signales_reste_bornee(self, caplog):
        """Sous un flot d'adresses distinctes, la table des pairs signalés reste sous son plafond."""
        with caplog.at_level(logging.WARNING):
            for i in range(rate_limit._MAX_WARNED_PEERS + 10):
                _client_key(_request(f"10.0.{i // 256}.{i % 256}", x_forwarded_for="203.0.113.9"))
        assert len(rate_limit._warned_peers) <= rate_limit._MAX_WARNED_PEERS

    def test_silence_quand_le_serveur_a_pris_l_en_tete(self, caplog):
        # Port nul : le serveur a réécrit l'adresse, le réglage est donc correct.
        with caplog.at_level(logging.WARNING):
            _client_key(_request("203.0.113.9", port=0, x_forwarded_for="203.0.113.9"))
        assert caplog.records == []

    def test_silence_sans_en_tete_de_proxy(self, caplog):
        with caplog.at_level(logging.WARNING):
            _client_key(_request("172.17.0.1"))
        assert caplog.records == []
