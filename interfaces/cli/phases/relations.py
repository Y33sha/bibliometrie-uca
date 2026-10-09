"""Câblage de la phase `relations`."""

from __future__ import annotations

from application.pipeline.context import Phase


def build() -> Phase:
    """Population des relations sémantiques entre publications distinctes.

    La phase suit `publications`, qui a rattaché les documents sources et permet de résoudre les DOI cibles en `publication_id`. Elle reconstruit `publication_relations` depuis les relations que les sources déclarent — `meta.related_identifiers` chez DataCite, `meta.relation` chez Crossref — complétées par les clés partagées et le rapprochement par titre. Les liens entre formes d'une même œuvre relèvent du dédoublonnage, en phase `metadata_correction`.
    """
    from application.pipeline.relations.phase import RelationsPhase
    from infrastructure.pipeline.relations import PgPublicationRelationsQueries

    return RelationsPhase(PgPublicationRelationsQueries())
