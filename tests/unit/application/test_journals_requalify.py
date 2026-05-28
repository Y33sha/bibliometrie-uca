"""Tests du service `requalify_publications_for_journal` (preview dry_run).

Le mode `dry_run=False` (apply) appelle `refresh_from_sources` complet et est exercé par les tests d'intégration ; ici on couvre la branche simulation, plus testable en isolation.
"""

from unittest.mock import MagicMock

from application.journals import requalify_publications_for_journal
from domain.publications.publication import Publication
from domain.source_publications.views import SourcePublicationWithJournalView


def _view(**overrides: object) -> SourcePublicationWithJournalView:
    defaults: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W42",
        "title": "T",
        "pub_year": 2024,
        "doc_type": "article",
        "doi": None,
        "journal_id": 7,
        "container_title": None,
        "language": None,
        "oa_status": None,
        "is_retracted": None,
        "abstract": None,
        "countries": (),
        "keywords": (),
        "urls": (),
        "topics": None,
        "biblio": None,
        "meta": None,
        "journal_type": "journal",
        "oa_model": None,
        "apc_amount": None,
    }
    defaults.update(overrides)
    return SourcePublicationWithJournalView(**defaults)  # type: ignore[arg-type]


def _pub(pub_id: int, doc_type: str) -> Publication:
    return Publication(id=pub_id, title="T", pub_year=2024, doc_type=doc_type, journal_id=7)


def test_empty_journal_returns_zero():
    pub_repo = MagicMock()
    pub_repo.find_ids_by_journal_id.return_value = []
    count = requalify_publications_for_journal(
        journal_id=7,
        prospective_journal_type="media",
        dry_run=True,
        pub_repo=pub_repo,
    )
    assert count == 0


def test_dry_run_counts_publications_that_would_flip_to_media():
    # Deux pubs rattachées à un journal qui passerait à media.
    # L'une est déjà en `media` (no-op), l'autre en `article` (flip à compter).
    pub_repo = MagicMock()
    pub_repo.find_ids_by_journal_id.return_value = [101, 102]
    pub_repo.find_by_id.side_effect = [_pub(101, "article"), _pub(102, "media")]
    pub_repo.get_source_publications.side_effect = [
        [_view(id=1001, doc_type="article")],
        [_view(id=1002, doc_type="media")],
    ]

    count = requalify_publications_for_journal(
        journal_id=7,
        prospective_journal_type="media",
        dry_run=True,
        pub_repo=pub_repo,
    )

    assert count == 1
    # Aucune persistance en dry_run.
    pub_repo.save.assert_not_called()


def test_dry_run_no_change_when_prospective_is_same_journal_type():
    # Le journal était déjà "journal" et on simule pour... "journal" : pas de flip.
    pub_repo = MagicMock()
    pub_repo.find_ids_by_journal_id.return_value = [101]
    pub_repo.find_by_id.return_value = _pub(101, "article")
    pub_repo.get_source_publications.return_value = [_view(doc_type="article")]

    count = requalify_publications_for_journal(
        journal_id=7,
        prospective_journal_type="journal",
        dry_run=True,
        pub_repo=pub_repo,
    )
    assert count == 0


def test_dry_run_skips_orphan_publications():
    # Une pub sans aucune source (cas pathologique) est ignorée, pas d'erreur.
    pub_repo = MagicMock()
    pub_repo.find_ids_by_journal_id.return_value = [101]
    pub_repo.find_by_id.return_value = _pub(101, "article")
    pub_repo.get_source_publications.return_value = []

    count = requalify_publications_for_journal(
        journal_id=7,
        prospective_journal_type="media",
        dry_run=True,
        pub_repo=pub_repo,
    )
    assert count == 0
