"""Câblage de la phase `metadata_correction`."""

from __future__ import annotations

from application.pipeline.context import Phase


def build() -> Phase:
    """Correction des métadonnées des documents sources.

    Séquence, transactions et métriques dans `application/pipeline/metadata_correction/phase.py`.
    """
    from application.pipeline.metadata_correction.phase import MetadataCorrectionPhase
    from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries

    return MetadataCorrectionPhase(PgMetadataCorrectionQueries())
