"""Câblage de la phase `metadata_correction`."""

from __future__ import annotations

from pipeline.context import Phase


def build() -> Phase:
    """Correction des métadonnées des documents sources.

    Séquence, transactions et métriques dans `pipeline/publications/metadata_correction.py`.
    """
    from pipeline.publications.metadata_correction import MetadataCorrectionPhase
    from pipeline.publications.metadata_correction_queries import PgMetadataCorrectionQueries

    return MetadataCorrectionPhase(PgMetadataCorrectionQueries())
