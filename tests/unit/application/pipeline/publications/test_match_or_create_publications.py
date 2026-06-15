"""Tests unitaires de `application.pipeline.publications.match_or_create_publications`.

Couvre :
- `process_document` : aiguillage DOI / NNT / HAL / thesis vers `decide_publication_match`.
- `run` : boucle d'orchestration, commit/rollback, dry-run, exceptions.

L'extraction des clés de confirmation (DOI effectif Zenodo, NNT/PMID/HAL) est portée par `domain.source_publications.keys.project_confirmation_keys`, testée dans `tests/unit/domain/source_publications/test_keys.py`. Les helpers de matching par métadonnées (cas thèse, etc.) sont testés dans `test_metadata_deduplication_rules.py`.

Mocks : port `PublicationsMatchOrCreateQueries`, `PublicationRepository`, `AuditRepository`. `refresh_from_sources` monkeypatché dans le module pour isoler la logique d'aiguillage.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import match_or_create_publications
from application.pipeline.publications.match_or_create_publications import (
    process_document,
    run,
)
from application.ports.pipeline.publications_match_or_create import SourcePublicationRow

# ── Helpers de mocking ───────────────────────────────────────────


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_match_or_create_publications")


def _make_doc(**overrides: Any) -> SourcePublicationRow:
    """Crée un doc avec valeurs par défaut acceptables pour `process_document`.

    `in_perimeter=True` par défaut (cas le plus courant) ; passer `in_perimeter=False` pour tester le gate `allow_create`.
    """
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
        "in_perimeter": True,
    }
    base.update(overrides)
    return SourcePublicationRow(**base)


@pytest.fixture
def captured(monkeypatch):
    """Monkeypatche `refresh_from_sources` du module pour capturer ses appels."""
    state: dict[str, Any] = {"refresh_calls": []}

    def fake_refresh(pub_id, *, repo, audit_repo=None):  # noqa: ARG001
        state["refresh_calls"].append(pub_id)

    monkeypatch.setattr(match_or_create_publications, "refresh_from_sources", fake_refresh)
    return state


class _PubByDoiStub:
    """Stub d'une publication trouvée par DOI : le matcher n'en lit que `.id`."""

    def __init__(self, id: int) -> None:
        self.id = id


# ── process_document ─────────────────────────────────────────────


class TestProcessDocumentEarlyReturns:
    def test_no_minimal_metadata_returns_skipped(self, captured, logger):
        """Title vide → outcome `skipped_no_metadata` sans appel à la DB."""
        queries = MagicMock()
        repo = MagicMock()
        doc = _make_doc(title="")

        result = process_document(conn=None, queries=queries, doc=doc, dry_run=False, pub_repo=repo)

        assert result == "skipped_no_metadata"
        repo.create.assert_not_called()

    def test_no_pub_year_returns_skipped(self, captured, logger):
        queries = MagicMock()
        repo = MagicMock()
        doc = _make_doc(pub_year=None)

        result = process_document(conn=None, queries=queries, doc=doc, dry_run=False, pub_repo=repo)

        assert result == "skipped_no_metadata"

    def test_dry_run_short_circuits_after_minimal_check(self, captured, logger):
        """Dry-run + métadonnées minimales OK → `created` (approximation) sans aucun appel DB."""
        queries = MagicMock()
        repo = MagicMock()

        result = process_document(
            conn=None, queries=queries, doc=_make_doc(), dry_run=True, pub_repo=repo
        )

        assert result == "created"
        repo.find_by_doi.assert_not_called()
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_not_called()


class TestProcessDocumentCreate:
    def test_no_match_creates_publication(self, captured, logger):
        """Aucun identifiant → action=create, link, refresh."""
        queries = MagicMock()
        queries.link_source_publication_to_publication = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = None
        repo.create.return_value = 4242

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(doc_type="article", source="openalex", source_id="W1"),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "created"
        repo.create.assert_called_once()
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 4242)
        assert captured["refresh_calls"] == [4242]


class TestProcessDocumentDoiMatch:
    def test_doi_links_to_existing_publication(self, captured, logger):
        """DOI pointant une publication existante → action=match sur son id.

        Plus d'arbitrage chapitre/ouvrage ici : la correction relationnelle a nullé
        a priori le DOI erroné sur la SP, donc un DOI présent = match positif direct.
        """
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = _PubByDoiStub(id=77)

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(doi="10.1/x"),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "linked"
        repo.create.assert_not_called()
        repo.find_by_doi.assert_called_once_with("10.1/x")
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 77)
        assert captured["refresh_calls"] == [77]

    def test_doi_not_found_falls_through_to_create(self, captured, logger):
        """DOI sans publication existante + pas d'autres clés → création, DOI conservé."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = None
        repo.create.return_value = 99

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(doi="10.1/x"),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "created"
        repo.create.assert_called_once()
        assert repo.create.call_args.kwargs["doi"] == "10.1/x"


class TestProcessDocumentZenodoConcept:
    """Approche B : le DOI canonique d'une SP Zenodo est son concept DOI."""

    def test_create_uses_concept_doi_not_version(self, captured, logger):
        """Sans pub existante : la pub est créée avec le concept DOI, pas la version."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = None
        repo.create.return_value = 7
        doc = _make_doc(
            doi="10.5281/zenodo.11",  # version
            external_ids={"zenodo_concept_doi": "10.5281/zenodo.10"},  # concept
        )

        result = process_document(conn=None, queries=queries, doc=doc, dry_run=False, pub_repo=repo)

        assert result == "created"
        # Lookup et création sur le concept DOI, jamais la version.
        repo.find_by_doi.assert_called_once_with("10.5281/zenodo.10")
        assert repo.create.call_args.kwargs["doi"] == "10.5281/zenodo.10"

    def test_version_links_to_existing_concept_publication(self, captured, logger):
        """Une SP version rejoint la publication portée par le concept DOI."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = _PubByDoiStub(id=42)
        doc = _make_doc(
            doi="10.5281/zenodo.11",
            external_ids={"zenodo_concept_doi": "10.5281/zenodo.10"},
        )

        result = process_document(conn=None, queries=queries, doc=doc, dry_run=False, pub_repo=repo)

        assert result == "linked"
        repo.find_by_doi.assert_called_once_with("10.5281/zenodo.10")
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 42)


class TestProcessDocumentNntMatch:
    def test_nnt_match_used_when_no_doi(self, captured, logger):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = 55
        repo.find_by_hal_id.return_value = None

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(
                doc_type="thesis",
                source="theses",
                source_id="2024UCFA0001",
                external_ids={"nnt": "2024UCFA0001"},
            ),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "linked"
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 55)


class TestProcessDocumentHalMatch:
    def test_hal_match_used_when_no_doi_no_nnt(self, captured, logger):
        """Le HAL ID est lu depuis `external_ids.hal_id` — convention symétrique avec NNT (theses), posée par le normalizer HAL au même titre que par OpenAlex/ScanR."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = 33

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(
                source="hal",
                source_id="hal-12345",
                external_ids={"hal_id": ["hal-12345"]},
            ),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "linked"
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 33)


class TestProcessDocumentThesisMetadata:
    def test_thesis_metadata_match_falls_through_to_decide(self, captured, logger, monkeypatch):
        """Thèse sans DOI/NNT/HAL mais titre+année compatibles → match via metadata."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = None
        repo.find_thesis_by_title.return_value = [123]
        queries.fetch_thesis_primary_author_from_source_publication.return_value = None
        queries.fetch_thesis_primary_author.return_value = None

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(doc_type="thesis", source="theses", source_id="theses-1"),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "linked"
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 123)


class TestProcessDocumentPerimeterGate:
    """Non-régression : la création est gated par `allow_create = doc["in_perimeter"]`, le matching est universel.

    Couvre le trou de couverture des conflits inter-sources : si HAL classe une publication hors-UCA alors qu'OpenAlex l'a classée UCA, la version HAL hors-périmètre doit pouvoir se rattacher (via DOI/NNT/HAL_ID) à la publication canonique créée par OpenAlex — et non créer un doublon ni être ignorée. À l'inverse, un orphelin hors-périmètre sans match ne doit pas faire entrer une nouvelle publication dans le périmètre.
    """

    def test_match_succeeds_outside_perimeter(self, captured, logger):
        """source_publication hors-périmètre + DOI matchant publi existante → linked, link + refresh appelés."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = _PubByDoiStub(id=99)

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(doi="10.1/x", in_perimeter=False),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "linked"
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_called_once_with(None, 1, 99)
        assert captured["refresh_calls"] == [99]

    def test_no_match_outside_perimeter_skips_creation(self, captured, logger):
        """source_publication hors-périmètre + aucun match → skipped_no_perimeter, ni create ni link ni refresh."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = None

        result = process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(in_perimeter=False),
            dry_run=False,
            pub_repo=repo,
        )

        assert result == "skipped_no_perimeter"
        repo.create.assert_not_called()
        queries.link_source_publication_to_publication.assert_not_called()
        assert captured["refresh_calls"] == []


class TestProcessDocumentTitleCleaning:
    def test_cleaned_title_used_when_changed(self, captured, logger, monkeypatch):
        """Si `clean_publication_title` modifie le titre (cas double-encodage), c'est la version nettoyée qui sert à `pub_repo.create`."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_by_doi.return_value = None
        repo.find_by_nnt.return_value = None
        repo.find_by_hal_id.return_value = None
        repo.create.return_value = 1

        # Forcer un titre nettoyé différent.
        monkeypatch.setattr(
            match_or_create_publications,
            "clean_publication_title",
            lambda t: "Titre & co",
        )

        process_document(
            conn=None,
            queries=queries,
            doc=_make_doc(title="Titre &amp;amp; co", doc_type="article", source="openalex"),
            dry_run=False,
            pub_repo=repo,
        )

        # `repo.create` reçoit le titre nettoyé.
        assert repo.create.call_args.kwargs["title"] == "Titre & co"


# ── run ──────────────────────────────────────────────────────────


@pytest.fixture
def patched_process(monkeypatch):
    """Monkeypatche `process_document` et `refresh_from_sources` au niveau du module pour isoler `run`."""
    state: dict[str, Any] = {
        "process_calls": [],
        "process_returns": [],  # Liste FIFO : un return par appel.
        "refresh_calls": [],
        "refresh_raises_on_id": None,
    }

    def fake_process(conn, queries, doc, dry_run, *, pub_repo, audit_repo=None):  # noqa: ARG001
        state["process_calls"].append({"doc_id": doc.id, "dry_run": dry_run})
        # Si pas de return programmé : "created" par défaut.
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
    def test_no_docs_no_stale_only_logs(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = []
        repo = MagicMock()

        run(conn, queries, logger, pub_repo=repo)

        assert patched_process["process_calls"] == []
        assert patched_process["refresh_calls"] == []
        # Run normal → commit final même sans travail.
        assert conn.committed is True

    def test_mixed_outcomes(self, patched_process, logger):
        """`process_document` retourne created/linked/skipped → tous les compteurs s'incrémentent sans crasher."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = [
            _make_doc(id=10),
            _make_doc(id=11),
            _make_doc(id=12),
            _make_doc(id=13),
        ]
        queries.fetch_stale_publication_ids.return_value = []
        repo = MagicMock()
        patched_process["process_returns"] = [
            "created",
            "linked",
            "skipped_no_metadata",
            "skipped_no_perimeter",
        ]

        run(conn, queries, logger, pub_repo=repo)

        assert [c["doc_id"] for c in patched_process["process_calls"]] == [10, 11, 12, 13]
        assert conn.committed is True

    def test_dry_run_rollbacks_at_end(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = [_make_doc(id=10)]
        queries.fetch_stale_publication_ids.return_value = []
        repo = MagicMock()

        run(conn, queries, logger, pub_repo=repo, dry_run=True)

        # Dry-run propagé.
        assert patched_process["process_calls"][0]["dry_run"] is True
        # Rollback final, pas de commit.
        assert conn.committed is False
        assert conn.rolled_back is True

    def test_stale_publications_refreshed(self, patched_process, logger):
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = [100, 200, 300]
        repo = MagicMock()

        run(conn, queries, logger, pub_repo=repo)

        assert patched_process["refresh_calls"] == [100, 200, 300]
        assert conn.committed is True

    def test_stale_intermediate_commit_every_500(self, patched_process, logger):
        """Passe 2 : commit intermédiaire tous les 500 refresh (hors dry-run)."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = list(range(1, 1001))
        repo = MagicMock()

        run(conn, queries, logger, pub_repo=repo)

        # Phase A end (1) + Phase B 4 steps (4) + stale intermediate à 500/1000 (2) + final (1) → 8.
        assert conn.commit_count == 8

    def test_intermediate_commit_every_500_docs(self, patched_process, logger):
        """Tous les 500 docs traités en Phase A, un commit intermédiaire est lancé (hors dry-run)."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = [
            _make_doc(id=i) for i in range(1, 1001)
        ]
        queries.fetch_stale_publication_ids.return_value = []
        repo = MagicMock()

        run(conn, queries, logger, pub_repo=repo)

        # Phase A intermediate à 500/1000 (2) + Phase A end (1) + Phase B 4 steps (4) + final (1) → 8.
        assert conn.commit_count == 8

    def test_refresh_exception_rollbacks_and_reraises(self, patched_process, logger):
        """Une exception dans `refresh_from_sources` (passe 2) → rollback + re-raise.

        Les commits des Phases A et B ont déjà persisté en amont — `committed`
        est True ; `rolled_back` couvre la transaction en cours au moment
        de l'exception.
        """
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.return_value = []
        queries.fetch_stale_publication_ids.return_value = [10, 20, 30]
        repo = MagicMock()
        patched_process["refresh_raises_on_id"] = 20

        with pytest.raises(RuntimeError, match="refresh boom on 20"):
            run(conn, queries, logger, pub_repo=repo)

        assert conn.rolled_back is True
        # Phase A end (1) + Phase B 4 steps (4) = 5 commits avant que la passe 2 (stale) plante.
        assert conn.commit_count == 5

    def test_top_level_exception_rollbacks_and_reraises(self, patched_process, logger):
        """Exception venant de `fetch_orphan_in_perimeter_source_publications` → rollback + re-raise."""
        conn = _FakeConn()
        queries = MagicMock()
        queries.fetch_orphan_in_perimeter_source_publications.side_effect = RuntimeError("boom")
        repo = MagicMock()

        with pytest.raises(RuntimeError, match="boom"):
            run(conn, queries, logger, pub_repo=repo)

        assert conn.rolled_back is True
        assert conn.committed is False
