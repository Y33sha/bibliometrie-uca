"""Enrichissement du pays des éditeurs depuis OpenAlex.

Le script assemble ce dont le cas d'usage a besoin — l'accès à la source, le disjoncteur qui borne les appels, le référentiel des éditeurs — et le laisse travailler. Deux propriétés lui appartiennent en propre : la connexion est refermée quoi qu'il arrive, et l'épuisement du quota quotidien de la source n'est pas une erreur du script, mais un report à la prochaine exécution.
"""

import logging
import sys
from types import SimpleNamespace

import pytest

from application.ports.pipeline.circuit_breaker import SourceUnavailableError
from interfaces.cli.maintenance import enrich_publishers as module
from interfaces.cli.maintenance.enrich_publishers import main


@pytest.fixture
def lancer(monkeypatch):
    """Neutralise la source et la base, et retient les arguments remis au cas d'usage."""

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
        monkeypatch.setattr(module, "publisher_repository", lambda c: object())
        monkeypatch.setattr(module, "run_enrich_publishers_from_openalex", _enrichir)
        monkeypatch.setattr(module, "get_openalex_api_key", lambda: "clé")
        monkeypatch.setattr(module, "get_polite_pool_email", lambda: "contact@uca.fr")
        monkeypatch.setattr(sys, "argv", ["enrich_publishers", *arguments])

        code = main()
        return SimpleNamespace(code=code, recus=recus, fermetures=fermetures)

    return _lancer


def test_enrichissement_lance_avec_ses_dependances(lancer):
    resultat = lancer()

    assert resultat.code == 0
    assert resultat.recus["limit"] == 0
    assert resultat.recus["dry_run"] is False
    assert resultat.recus["breaker"] is not None
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
    assert "à relancer plus tard" in caplog.text
    assert resultat.fermetures == [True]
