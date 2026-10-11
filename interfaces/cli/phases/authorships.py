"""Câblage de la phase `authorships`."""

from __future__ import annotations

from application.pipeline.context import Phase
from application.pipeline.metrics import PhaseMetrics
from interfaces.cli.phases.execution import log, open_tx


def build() -> Phase:
    """Construction du référentiel `authorships`.

    Les signatures des sources se consolident en une entrée par couple publication-personne, avec son appartenance au périmètre ; les structures dérivent de la matview `authorship_structures`. Après les dernières suppressions de publications, les monographies, revues et éditeurs vides sont supprimés.

    La phase reconsolide toutes les sources à chaque run et ignore `--sources` : une signature se trouve modifiée par d'autres voies que sa propre normalisation, comme la repopulation des affiliations ou le recalcul des métadonnées d'une publication.

    Une passe unique ajoute les liens attestés, retire les liens sans attestation et recalcule les attributs, de sorte que la table converge sans être vidée. `run_pipeline --rebuild-authorships` la purge et la reconstruit depuis zéro, en récupération.

    Séquence, transactions et métriques dans `application/pipeline/authorships/phase.py`.
    """
    from application.pipeline.authorships.phase import AuthorshipsPhase
    from application.pipeline.publishers_journals import (
        delete_empty_journals,
        delete_empty_monographs,
        delete_empty_publishers,
    )
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
        empty_containers=(
            (delete_empty_monographs.LIBELLE, _run_delete_empty_monographs),
            (delete_empty_journals.LIBELLE, _run_delete_empty_journals),
            (delete_empty_publishers.LIBELLE, _run_delete_empty_publishers),
        ),
    )


def _run_delete_empty_monographs() -> PhaseMetrics:
    from application.pipeline.publishers_journals.delete_empty_monographs import (
        run_delete_empty_monographs,
    )
    from infrastructure.pipeline.monographs import PgMonographGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_monographs(log, monograph_repo=PgMonographGatewayQueries(conn))


def _run_delete_empty_journals() -> PhaseMetrics:
    from application.pipeline.publishers_journals.delete_empty_journals import (
        run_delete_empty_journals,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_journals(log, journal_repo=PgJournalGatewayQueries(conn))


def _run_delete_empty_publishers() -> PhaseMetrics:
    from application.pipeline.publishers_journals.delete_empty_publishers import (
        run_delete_empty_publishers,
    )
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_publishers(log, publisher_repo=PgPublisherGatewayQueries(conn))
