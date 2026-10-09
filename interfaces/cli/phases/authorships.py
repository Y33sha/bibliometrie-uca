"""Câblage de la phase `authorships`."""

from __future__ import annotations

from application.pipeline.context import Phase


def build() -> Phase:
    """Construction du référentiel `authorships`.

    Les signatures des sources se consolident en une entrée par couple publication-personne, avec son appartenance au périmètre ; les structures dérivent de la matview `authorship_structures`.

    La phase reconsolide toutes les sources à chaque run et ignore `--sources` : une signature se trouve modifiée par d'autres voies que sa propre normalisation, comme la repopulation des affiliations ou le recalcul des métadonnées d'une publication.

    Une passe unique ajoute les liens attestés, retire les liens sans attestation et recalcule les attributs, de sorte que la table converge sans être vidée. `run_pipeline --rebuild-authorships` la purge et la reconstruit depuis zéro, en récupération.

    Séquence, transactions et métriques dans `application/pipeline/authorships/phase.py`.
    """
    from application.pipeline.authorships.phase import AuthorshipsPhase
    from infrastructure.pipeline.authorships.address_pub_count import PgAddressPubCountQueries
    from infrastructure.pipeline.authorships.build import PgAuthorshipsBuildQueries
    from infrastructure.pipeline.authorships.pub_counts import PgPubCountsQueries
    from infrastructure.pipeline.authorships.purge_orphan_publications import (
        PgPurgeOrphanPublicationsQueries,
    )

    return AuthorshipsPhase(
        PgAuthorshipsBuildQueries(),
        PgPurgeOrphanPublicationsQueries(),
        PgPubCountsQueries(),
        PgAddressPubCountQueries(),
    )
