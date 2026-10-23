"""Enrichissement du pays des éditeurs depuis OpenAlex.

Le script se referme sur sa connexion quoi qu'il arrive, et l'épuisement du quota quotidien de la source est un report à la prochaine exécution, pas une erreur. La boucle par lots s'arrête dès que le circuit-breaker de source est déclenché.
"""

import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from interfaces.cli.maintenance import enrich_publishers as module
from interfaces.cli.maintenance.enrich_publishers import main
from pipeline.http.circuit_breaker import (
    SourceUnavailableError,
    get_current_breaker,
    source_circuit_breaker,
)
from pipeline.ingestion.openalex import api


@pytest.fixture
def lancer(monkeypatch):
    """Neutralise la source et la base, et retient les arguments remis à la boucle."""

    def _lancer(*arguments, issue=None):
        conn = SimpleNamespace(close=lambda: fermetures.append(True))
        fermetures: list[bool] = []
        recus: dict = {}

        def _enrichir(c, logger, **kw):
            recus.update(kw)
            if issue is not None:
                raise issue

        monkeypatch.setattr(
            module, "get_sync_engine", lambda: SimpleNamespace(connect=lambda: conn)
        )
        monkeypatch.setattr(module, "run_enrich_publishers_from_openalex", _enrichir)
        monkeypatch.setattr(module, "source_credentials_missing", lambda s: None)
        monkeypatch.setattr(sys, "argv", ["enrich_publishers", *arguments])

        code = main()
        return SimpleNamespace(code=code, recus=recus, fermetures=fermetures)

    return _lancer


def test_enrichissement_lance_avec_ses_dependances(lancer):
    resultat = lancer()

    assert resultat.code == 0
    assert resultat.recus["limit"] == 0
    assert resultat.recus["dry_run"] is False
    assert resultat.fermetures == [True]


def test_options_transmises(lancer):
    resultat = lancer("--limit", "50", "--dry-run")

    assert resultat.recus["limit"] == 50
    assert resultat.recus["dry_run"] is True


def test_quota_de_la_source_epuise(lancer, caplog):
    """Le quota du jour épuisé n'est pas un échec : le reste est reporté, la connexion refermée."""
    with caplog.at_level(logging.WARNING):
        resultat = lancer(issue=SourceUnavailableError("openalex"))

    assert resultat.code == 0
    assert "openalex indisponible" in caplog.text
    assert resultat.fermetures == [True]


class TestArretSurCoupeCircuit:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr(module.time, "sleep", lambda *_: None)

    def _run(self, monkeypatch, fetch_batch, n_batches):
        conn = MagicMock()
        rows = [(i, f"P{i}") for i in range(n_batches * module.BATCH_SIZE)]
        monkeypatch.setattr(module, "find_countryless", lambda c, limit=None: rows)
        with source_circuit_breaker("openalex"):
            module.run_enrich_publishers_from_openalex(conn, MagicMock(), fetch_batch=fetch_batch)
        return conn

    def test_s_arrete_quand_le_coupe_circuit_se_declenche(self, monkeypatch):
        """La boucle s'arrête au tour où le breaker est déclenché, sans parcourir tout le stock."""
        calls = {"n": 0}

        def fetch_batch(_oa_ids):
            calls["n"] += 1
            if calls["n"] >= 3 and (breaker := get_current_breaker()) is not None:
                breaker.tripped = True  # le 3e lot épuise le budget
            return {}

        conn = self._run(monkeypatch, fetch_batch, n_batches=20)
        assert calls["n"] == 3
        conn.commit.assert_called()  # le déjà-fait est committé avant de couper

    def test_parcourt_tous_les_lots_quand_la_source_tient(self, monkeypatch):
        calls = {"n": 0}

        def fetch_batch(_oa_ids):
            calls["n"] += 1
            return {}

        self._run(monkeypatch, fetch_batch, n_batches=4)
        assert calls["n"] == 4


class TestExtractCountry:
    def test_premier_code_en_minuscule(self):
        assert module.extract_country({"id": "P1", "country_codes": ["FR", "DE"]}) == "fr"

    def test_none_quand_la_liste_est_vide(self):
        assert module.extract_country({"id": "P1", "country_codes": []}) is None

    def test_none_quand_le_champ_est_absent(self):
        assert module.extract_country({"id": "P1"}) is None


class TestFetchPublishersBatch:
    def _payload(self, *publishers):
        return {"results": list(publishers)}

    def test_associe_identifiant_court_et_pays(self, monkeypatch):
        payload = self._payload(
            {"id": "https://openalex.org/P1", "country_codes": ["NL"]},
            {"id": "https://openalex.org/P2", "country_codes": []},
        )
        monkeypatch.setattr(module, "http_request_with_retry", lambda *a, **k: payload)
        out = module.fetch_publishers_batch(["P1", "P2"], openalex_publishers_api="x")
        assert out == {"P1": "nl", "P2": None}

    def test_un_editeur_absent_de_la_reponse_reste_absent(self, monkeypatch):
        """`None` dit « la source ne connaît pas de pays » ; l'absence de clé dit « la source n'a rien répondu »."""
        payload = self._payload({"id": "https://openalex.org/P1", "country_codes": ["FR"]})
        monkeypatch.setattr(module, "http_request_with_retry", lambda *a, **k: payload)
        out = module.fetch_publishers_batch(["P1", "P2"], openalex_publishers_api="x")
        assert out == {"P1": "fr"}

    def test_dictionnaire_vide_sur_echec(self, monkeypatch):
        """L'échec est déjà compté au circuit-breaker par le helper HTTP : le lot rendu est vide."""

        def boom(*_a, **_k):
            raise SourceUnavailableError("openalex")

        monkeypatch.setattr(module, "http_request_with_retry", boom)
        assert module.fetch_publishers_batch(["P1"], openalex_publishers_api="x") == {}

    def test_la_cle_d_api_prime_sur_l_adresse_polite_pool(self, monkeypatch):
        captured: dict = {}

        def capture(*_a, **kwargs):
            captured.update(kwargs["params"])
            return {"results": []}

        monkeypatch.setattr(module, "http_request_with_retry", capture)
        monkeypatch.setattr(api, "get_openalex_api_key", lambda: "cle")
        monkeypatch.setattr(api, "get_polite_pool_email_optional", lambda: "m@example.org")
        module.fetch_publishers_batch(["P1"], openalex_publishers_api="x")
        assert captured["api_key"] == "cle"
        assert "mailto" not in captured
