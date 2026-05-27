"""Tests du contrat de `effective_metadata` (correction des métadonnées canoniques).

Phase 1 du chantier METIER_metadata-correction : aucune règle figée. Les tests vérifient que le stub respecte son contrat (renvoie un `CorrectedFields` vide) et que les types auxiliaires (`Correction`, `CorrectedFields`) fonctionnent. Les tests par règle viendront s'ajouter aux phases suivantes.
"""

from domain.publications.correction import (
    CorrectedFields,
    effective_metadata,
)
from domain.source_publications.source_publication import SourcePublication


class TestCorrectedFields:
    def test_is_empty_on_default(self):
        assert CorrectedFields().is_empty()

    # Tests `is_not_empty` à ajouter en Phase 2+ une fois qu'au moins un membre de `MetadataCorrectionRule` est figé (l'enum est vide en Phase 1).


class TestEffectiveMetadataStub:
    """Phase 1 — `effective_metadata` est un stub no-op : retourne toujours `CorrectedFields()` vide, quelles que soient la SP et les entités fournies."""

    def _sp(self, **overrides: object) -> SourcePublication:
        defaults: dict[str, object] = {
            "id": 1,
            "source": "openalex",
            "source_id": "W42",
            "title": "Some title",
        }
        defaults.update(overrides)
        return SourcePublication(**defaults)  # type: ignore[arg-type]

    def test_returns_empty_corrected_fields_for_minimal_sp(self):
        assert effective_metadata(self._sp()).is_empty()

    def test_returns_empty_corrected_fields_with_journal_and_publisher_none(self):
        assert effective_metadata(self._sp(), journal=None, publisher=None).is_empty()

    def test_returns_empty_corrected_fields_regardless_of_sp_fields(self):
        sp = self._sp(
            doc_type="article",
            doi="10.1234/x",
            journal_id=42,
            oa_status="gold",
            pub_year=2024,
        )
        assert effective_metadata(sp).is_empty()
