"""Tests unitaires de la couche application des publications.

Re-correction canonique (`_apply_canonical_corrections`) : découplage de l'arbitrage — les champs canoniques peuvent provenir de `source_publications` différentes ; une correction journal-dépendante appliquée par source ne suit pas le `journal_id` canonique. La re-correction la rejoue sur le journal réellement résolu.

Frontière transactionnelle de la fusion (`commands.merge_publications`) : la cible n'est recomposée qu'une fois.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from application.ports.repositories.publication_repository import JournalCorrectionInputs
from application.services.publications import commands, core
from application.services.publications.core import _apply_canonical_corrections
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication


class _FakeRepo:
    """Repo minimal : le helper n'appelle que `get_journal_correction_inputs`."""

    def __init__(self, journal_type: str | None = None, oa_model: str | None = None) -> None:
        self._inputs = JournalCorrectionInputs(journal_type=journal_type, oa_model=oa_model)

    def get_journal_correction_inputs(self, journal_id: int | None) -> JournalCorrectionInputs:
        return JournalCorrectionInputs() if journal_id is None else self._inputs


def _pub(**overrides: object) -> Publication:
    defaults: dict[str, object] = {
        "id": 1,
        "title": "Un titre",
        "pub_year": 2020,
        "doc_type": "preprint",
        "journal_id": 7,
    }
    defaults.update(overrides)
    return Publication(**defaults)  # type: ignore[arg-type]


def test_journal_type_media_decoupling_is_repaired():
    # doc_type arbitré = preprint (d'une SP sans journal), journal_id arbitré = un journal média
    # (d'une autre SP) : la re-correction applique JOURNAL_TYPE_MEDIA_TO_MEDIA au journal résolu.
    pub = _pub(doc_type="preprint", journal_id=7)
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="media"))
    assert pub.doc_type == "media"
    assert pub.meta == {"corrections": {"doc_type": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}}


def test_no_journal_id_no_change():
    pub = _pub(doc_type="preprint", journal_id=None)
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="media"))
    assert pub.doc_type == "preprint"
    assert pub.meta is None


def test_journal_type_without_rule_leaves_doc_type():
    # journal_type='journal' : aucune règle journal-dépendante → pas de correction.
    pub = _pub(doc_type="preprint", journal_id=7)
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="journal"))
    assert pub.doc_type == "preprint"
    assert pub.meta is None


def test_full_cascade_replayed_thesis_with_publisher_doi():
    # La re-correction rejoue toute la cascade : thèse + journal_id + DOI éditeur → article.
    pub = _pub(doc_type="thesis", journal_id=7, doi=DOI("10.1016/j.ex.2020.01.001"))
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="journal"))
    assert pub.doc_type == "article"
    assert pub.meta == {"corrections": {"doc_type": "THESIS_WITH_JOURNAL_TO_ARTICLE"}}


def test_thesis_with_abes_doi_stays_thesis():
    pub = _pub(doc_type="thesis", journal_id=7, doi=DOI("10.70675/abc"))
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="journal"))
    assert pub.doc_type == "thesis"
    assert pub.meta is None


def test_full_oa_journal_promotes_hybrid_to_gold():
    # oa_status arbitré = hybrid (posé par défaut au normalize sur une SP sans journal résolu),
    # journal_id arbitré = une revue full-OA (d'une autre SP) : HYBRID_FULL_OA_TO_GOLD se rejoue
    # sur l'oa_model du journal résolu.
    pub = _pub(doc_type="article", journal_id=7, oa_status="hybrid")
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="journal", oa_model="full_oa"))
    assert pub.oa_status == "gold"
    assert pub.meta == {"corrections": {"oa_status": "HYBRID_FULL_OA_TO_GOLD"}}


def test_hybrid_in_hybrid_journal_stays_hybrid():
    pub = _pub(doc_type="article", journal_id=7, oa_status="hybrid")
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="journal", oa_model="hybrid"))
    assert pub.oa_status == "hybrid"
    assert pub.meta is None


def test_no_journal_id_leaves_oa_status():
    # Sans journal résolu, aucun oa_model à lire : la règle reste muette.
    pub = _pub(doc_type="article", journal_id=None, oa_status="hybrid")
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="journal", oa_model="full_oa"))
    assert pub.oa_status == "hybrid"
    assert pub.meta is None


def test_both_fields_corrected_are_traced_together():
    # Une même publication peut porter les deux incohérences d'arbitrage.
    pub = _pub(doc_type="preprint", journal_id=7, oa_status="hybrid")
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="media", oa_model="full_oa"))
    assert pub.doc_type == "media"
    assert pub.oa_status == "gold"
    assert pub.meta == {
        "corrections": {
            "doc_type": "JOURNAL_TYPE_MEDIA_TO_MEDIA",
            "oa_status": "HYBRID_FULL_OA_TO_GOLD",
        }
    }


def test_meta_preserved_when_correction_added():
    pub = _pub(doc_type="preprint", journal_id=7, meta={"k": "v"})
    _apply_canonical_corrections(pub, repo=_FakeRepo(journal_type="media"))
    assert pub.meta == {"k": "v", "corrections": {"doc_type": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}}


def test_merge_handler_recomposes_target_once(monkeypatch):
    """Le handler de fusion recompose la cible une seule fois : `refresh_from_sources` vit dans `core.merge_publications`, que le handler appelle sans le doubler."""
    calls: list[int] = []
    monkeypatch.setattr(core, "refresh_from_sources", lambda *a, **k: calls.append(1))
    repo = MagicMock()
    repo.find_by_id.return_value = SimpleNamespace(doi=None)
    commands.merge_publications(MagicMock(), 1, 2, repo=repo, audit_repo=MagicMock())
    assert calls == [1]
    repo.merge_into.assert_called_once_with(1, 2)
