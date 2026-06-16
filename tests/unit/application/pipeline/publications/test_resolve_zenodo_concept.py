"""Tests de l'orchestrateur de résolution du concept DOI Zenodo.

Couvre : résolution nominale, fallback self-concept (dépôt non versionné →
on pose le DOI propre), et skip sur erreur temporaire. Fakes en mémoire,
pas de DB ni de réseau.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from application.pipeline.publications.resolve_zenodo_concept import run
from application.ports.pipeline.zenodo_concept import ZenodoSourcePublication
from domain.sources.zenodo import ZenodoResolutionError


class _FakeQueries:
    def __init__(self, docs: list[ZenodoSourcePublication]) -> None:
        self._docs = docs
        self.set_calls: list[tuple[int, str]] = []

    def fetch_zenodo_source_publications_without_concept(self, conn):
        return self._docs

    def set_concept_doi(self, conn, source_publication_id: int, concept_doi: str) -> None:
        self.set_calls.append((source_publication_id, concept_doi))


class _FakeResolver:
    def __init__(self, mapping: dict[str, str | None], errors: set[str] = frozenset()) -> None:
        self._mapping = mapping
        self._errors = errors
        self.calls = 0

    def resolve_concept_doi(self, doi: str) -> str | None:
        self.calls += 1
        if doi in self._errors:
            raise ZenodoResolutionError("boom")
        return self._mapping.get(doi)


_LOG = logging.getLogger("test")


def test_resolves_concept_for_each_doc():
    docs = [
        ZenodoSourcePublication(id=1, doi="10.5281/zenodo.11"),
        ZenodoSourcePublication(id=2, doi="10.5281/zenodo.22"),
    ]
    queries = _FakeQueries(docs)
    resolver = _FakeResolver(
        {"10.5281/zenodo.11": "10.5281/zenodo.10", "10.5281/zenodo.22": "10.5281/zenodo.20"}
    )
    run(MagicMock(), queries, resolver, _LOG)
    assert queries.set_calls == [(1, "10.5281/zenodo.10"), (2, "10.5281/zenodo.20")]


def test_self_concept_fallback_when_no_concept():
    """Pas de concept exposé → on pose le DOI de la SP comme son propre concept."""
    docs = [ZenodoSourcePublication(id=7, doi="10.5281/zenodo.77")]
    queries = _FakeQueries(docs)
    resolver = _FakeResolver({"10.5281/zenodo.77": None})
    run(MagicMock(), queries, resolver, _LOG)
    assert queries.set_calls == [(7, "10.5281/zenodo.77")]


def test_temporary_error_skips_without_storing():
    docs = [
        ZenodoSourcePublication(id=1, doi="10.5281/zenodo.11"),
        ZenodoSourcePublication(id=2, doi="10.5281/zenodo.22"),
    ]
    queries = _FakeQueries(docs)
    resolver = _FakeResolver(
        {"10.5281/zenodo.22": "10.5281/zenodo.20"}, errors={"10.5281/zenodo.11"}
    )
    run(MagicMock(), queries, resolver, _LOG)
    # SP 1 en erreur → non stockée ; SP 2 résolue.
    assert queries.set_calls == [(2, "10.5281/zenodo.20")]


def test_circuit_breaks_after_consecutive_failures():
    """Régression : Zenodo down (échecs consécutifs) → coupe après le seuil, ne grince pas
    sur tout le stock (sinon 2376 × ~10s de timeout)."""
    from application.pipeline.publications.resolve_zenodo_concept import _CONSECUTIVE_FAILURES_MAX

    dois = [f"10.5281/zenodo.{i}" for i in range(50)]
    docs = [ZenodoSourcePublication(id=i, doi=d) for i, d in enumerate(dois)]
    queries = _FakeQueries(docs)
    resolver = _FakeResolver({}, errors=set(dois))  # tout échoue

    run(MagicMock(), queries, resolver, _LOG)

    assert resolver.calls == _CONSECUTIVE_FAILURES_MAX  # coupe au seuil, pas 50
    assert queries.set_calls == []


def test_strike_counter_resets_on_success():
    """Un succès entre des erreurs remet le compteur à zéro (pas de coupe prématurée)."""
    dois = [f"10.5281/zenodo.{i}" for i in range(5)]
    docs = [ZenodoSourcePublication(id=i, doi=d) for i, d in enumerate(dois)]
    queries = _FakeQueries(docs)
    # err, err, ok, err, err : max 2 échecs consécutifs < seuil → pas de coupe.
    resolver = _FakeResolver(
        {dois[2]: "10.5281/zenodo.concept"},
        errors={dois[0], dois[1], dois[3], dois[4]},
    )

    run(MagicMock(), queries, resolver, _LOG)

    assert resolver.calls == 5  # tout le stock parcouru
    assert queries.set_calls == [(2, "10.5281/zenodo.concept")]
