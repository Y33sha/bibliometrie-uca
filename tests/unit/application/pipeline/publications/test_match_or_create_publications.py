"""Tests unitaires de `application.pipeline.publications.match_or_create_publications`.

Couvre :
- `extract_known_identifiers` : helper pur (cf. `TestExtractKnownIdentifiers`).
- `process_document` : création seule (modèle création⇒fusion) — early-returns, corrections, concept DOI Zenodo, nettoyage de titre.
- `run` : boucle de création + refresh des stale, commit/rollback, dry-run, exceptions.

Mocks : port `PublicationsMatchOrCreateQueries`, `PublicationRepository`. `refresh_from_sources` monkeypatché pour isoler la logique.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import match_or_create_publications
from application.pipeline.publications.match_or_create_publications import (
    extract_known_identifiers,
    process_document,
    run,
)
from application.ports.pipeline.publications_match_or_create import SourcePublicationRow


class TestExtractKnownIdentifiers:
    def test_returns_external_ids_as_is(self):
        """Valeurs str non vides retenues ; `hal_id` (liste) est ignoré ici — lu à part
        dans `process_document` car multivalué."""
        assert extract_known_identifiers(
            {"hal_id": ["hal-X"], "nnt": "2021CLFAC030", "pmid": "12345"}
        ) == {
            "nnt": "2021CLFAC030",
            "pmid": "12345",
        }

    def test_ignores_non_str_values(self):
        """`external_ids` peut contenir des listes (issn/isbn Crossref) ou None — on les ignore ici."""
        assert extract_known_identifiers(
            {"issn": ["0028-0836"], "nnt": None, "pmid": "12345"},
        ) == {"pmid": "12345"}

    def test_ignores_empty_strings(self):
        assert extract_known_identifiers({"hal_id": ""}) == {}

    def test_empty_external_ids(self):
        assert extract_known_identifiers({}) == {}

    def test_none_external_ids(self):
        assert extract_known_identifiers(None) == {}


# ── Helpers de mocking ───────────────────────────────────────────


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_match_or_create_publications")


def _make_doc(**overrides: Any) -> SourcePublicationRow:
    """Crée un doc avec valeurs par défaut acceptables pour `process_document`."""
    base: dict[str, Any] = {
        "id": 1,
        "title": "Some title",
        "pub_year": 2024,
        "doi": None,
        "source": "openalex",
        "doc_type": "article",
        "journal_id": None,
        "oa_status": "closed",
        "language": "en",
        "container_title": None,
        "source_id": "W123",
        "external_ids": None,
        "urls": None,
    }
    base.update(overrides)
    return SourcePublicationRow(**base)


@pytest.fixture
def captured(monkeypatch):
    """Monkeypatche `refresh_from_sources` du module pour capturer les appels."""
    state: dict[str, Any] = {"refresh_calls": []}

    def fake_refresh(pub_id, *, repo, audit_repo=None):  # noqa: ARG001
        state["refresh_calls"].append(pub_id)

    monkeypatch.setattr(match_or_create_publications, "refresh_from_sources", fake_refresh)
    return state


# ── process_document ─────────────────────────────────────────────


class TestProcessDocumentEarlyReturns:
    def test_no_minimal_metadata_returns_skipped(self, captured, logger):
        """Title vide → outcome `skipped_no_metadata` sans création."""
        repo = MagicMock()
        result = process_document(
            conn=None, queries=MagicMock(), doc=_make_doc(title=""), dry_run=False, pub_repo=repo
        )
        assert result == "skipped_no_metadata"
        repo.create.assert_not_called()

    def test_no_pub_year_returns_skipped(self, captured, logger):
        result = process_document(
            conn=None,
            queries=MagicMock(),
            doc=_make_doc(pub_year=None),
            dry_run=False,
            pub_repo=MagicMock(),
        )
        assert result == "skipped_no_metadata"

    def test_dry_run_short_circuits(self, captured, logger):
        """Dry-run + métadonnées OK → `created` sans aucun appel DB."""
        queries = MagicMock()
        repo = MagicMock()
        result = process_document(
            conn=None, queries=queries, doc=_make_doc(), dry_run=True, pub_repo=repo
        )
        assert result == "created"
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_not_called()


class TestProcessDocumentCreate:
    def test_creates_links_refreshes(self, captured, logger):
        """Création de la publication, rattachement de la SP, refresh."""
        queries = MagicMock()
        repo = MagicMock()
        repo.create.return_value = 4242

        result = process_document(
            conn=None, queries=queries, doc=_make_doc(source_id="W1"), dry_run=False, pub_repo=repo
        )

        assert result == "created"
        repo.create.assert_called_once()
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 4242)
        assert captured["refresh_calls"] == [4242]

    def test_create_passes_doi(self, captured, logger):
        queries = MagicMock()
        repo = MagicMock()
        repo.create.return_value = 7
        process_document(
            conn=None, queries=queries, doc=_make_doc(doi="10.1/x"), dry_run=False, pub_repo=repo
        )
        assert repo.create.call_args.kwargs["doi"] == "10.1/x"


class TestProcessDocumentZenodoConcept:
    """Le DOI canonique d'une SP Zenodo est son concept DOI (résolu en amont)."""

    def test_create_uses_concept_doi_not_version(self, captured, logger):
        queries = MagicMock()
        repo = MagicMock()
        repo.create.return_value = 7
        doc = _make_doc(
            doi="10.5281/zenodo.11",  # version
            external_ids={"zenodo_concept_doi": "10.5281/zenodo.10"},  # concept
        )

        result = process_document(conn=None, queries=queries, doc=doc, dry_run=False, pub_repo=repo)

        assert result == "created"
        # Création sur le concept DOI, jamais la version (concept + versions
        # convergent ensuite via la fusion par DOI).
        assert repo.create.call_args.kwargs["doi"] == "10.5281/zenodo.10"


class TestProcessDocumentTitleCleaning:
    def test_cleaned_title_used_when_changed(self, captured, logger, monkeypatch):
        """Si `clean_publication_title` modifie le titre (double-encodage), c'est la
        version nettoyée qui sert à `pub_repo.create`."""
        queries = MagicMock()
        repo = MagicMock()
        repo.create.return_value = 1
        monkeypatch.setattr(
            match_or_create_publications, "clean_publication_title", lambda t: "Titre & co"
        )

        process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(title="Titre &amp;amp; co"),
            dry_run=False,
            pub_repo=repo,
        )

        assert repo.create.call_args.kwargs["title"] == "Titre & co"


# ── run ──────────────────────────────────────────────────────────


@pytest.fixture
def patched_process(monkeypatch):
    """Monkeypatche `process_document` et `refresh_from_sources` pour isoler `run`."""
    state: dict[str, Any] = {
        "process_calls": [],
        "process_returns": [],  # FIFO : un return par appel.
        "refresh_calls": [],
        "refresh_raises_on_id": None,
    }

    def fake_process(conn, queries, doc, dry_run, *, pub_repo, audit_repo=None):  # noqa: ARG001
        state["process_calls"].append({"doc_id": doc.id, "dry_run": dry_run})
        if state["process_returns"]:
            return state["process_returns"].pop(0)
        return "created"

    def fake_refresh(pub_id, *, repo, audit_repo=None):  # noqa: ARG001
        state["refresh_calls"].append(pub_id)
        if state["refresh_raises_on_id"] == pub_id:
            raise RuntimeError(f"refresh boom on {pub_id}")

    monkeypatch.setattr(match_or_create_publications, "process_document", fake_process)
    monkeypatch.setattr(match_or_create_publications, "refresh_from_sources", fake_refresh)
    return state


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.commit_count = 0

    def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    def rollback(self) -> None:
        self.rolled_back = True


class TestRun:
    def test_no_docs_no_stale_commits(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = []

        run(conn, queries, logger, pub_repo=MagicMock())

        assert patched_process["process_calls"] == []
        assert patched_process["refresh_calls"] == []
        assert conn.committed is True

    def test_creates_and_counts(self, patched_process, logger):
        """`process_document` retourne created/skipped → tous traités, commit final."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = [
            _make_doc(id=10),
            _make_doc(id=11),
            _make_doc(id=12),
        ]
        queries.fetch_stale_publication_ids.return_value = []
        patched_process["process_returns"] = ["created", "skipped_no_metadata", "created"]

        run(conn, queries, logger, pub_repo=MagicMock())

        assert [c["doc_id"] for c in patched_process["process_calls"]] == [10, 11, 12]
        assert conn.committed is True

    def test_dry_run_rollbacks_at_end(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = [_make_doc(id=10)]
        queries.fetch_stale_publication_ids.return_value = []

        run(conn, queries, logger, pub_repo=MagicMock(), dry_run=True)

        assert patched_process["process_calls"][0]["dry_run"] is True
        assert conn.committed is False
        assert conn.rolled_back is True

    def test_stale_publications_refreshed(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = [100, 200, 300]

        run(conn, queries, logger, pub_repo=MagicMock())

        assert patched_process["refresh_calls"] == [100, 200, 300]
        assert conn.committed is True

    def test_intermediate_commit_every_500_docs(self, patched_process, logger):
        """Tous les 500 docs créés, un commit intermédiaire (hors dry-run)."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = [
            _make_doc(id=i) for i in range(1, 1001)
        ]
        queries.fetch_stale_publication_ids.return_value = []

        run(conn, queries, logger, pub_repo=MagicMock())

        # create intermédiaire à 500/1000 (2) + create-final (1) + stale-final (1) = 4.
        assert conn.commit_count == 4

    def test_stale_intermediate_commit_every_500(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = list(range(1, 1001))

        run(conn, queries, logger, pub_repo=MagicMock())

        # create-final (1) + stale intermédiaire à 500/1000 (2) + stale-final (1) = 4.
        assert conn.commit_count == 4

    def test_refresh_exception_rollbacks_and_reraises(self, patched_process, logger):
        """Une exception dans `refresh_from_sources` → rollback + re-raise."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = [10, 20, 30]
        patched_process["refresh_raises_on_id"] = 20

        with pytest.raises(RuntimeError, match="refresh boom on 20"):
            run(conn, queries, logger, pub_repo=MagicMock())

        assert conn.rolled_back is True
        # create-final (1) avant que la passe stale plante (3 items, pas d'intermédiaire).
        assert conn.commit_count == 1

    def test_top_level_exception_rollbacks_and_reraises(self, patched_process, logger):
        """Exception venant de `fetch_orphan_source_publications` → rollback + re-raise."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_source_publications.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run(conn, queries, logger, pub_repo=MagicMock())

        assert conn.rolled_back is True
        assert conn.committed is False
