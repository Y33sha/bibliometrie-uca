"""Câblage de la phase `authorships`."""

from __future__ import annotations

from interfaces.cli.phases.execution import log, open_tx
from pipeline.context import Phase
from pipeline.metrics import PhaseMetrics


def build() -> Phase:
    """Construction du référentiel `authorships`.

    Les signatures des sources se consolident en une entrée par couple publication-personne, avec son appartenance au périmètre ; les structures dérivent de la matview `authorship_structures`. Après les dernières suppressions de publications, les monographies, revues et éditeurs vides sont supprimés.

    La phase reconsolide toutes les sources à chaque run et ignore `--sources` : une signature se trouve modifiée par d'autres voies que sa propre normalisation, comme la repopulation des affiliations ou le recalcul des métadonnées d'une publication.

    Une passe unique ajoute les liens attestés, retire les liens sans attestation et recalcule les attributs, de sorte que la table converge sans être vidée. `run_pipeline --rebuild-authorships` la purge et la reconstruit depuis zéro, en récupération.

    Séquence, transactions et métriques dans `pipeline/publications/authorships.py`.
    """
    from infrastructure.pipeline.authorships.build import PgAuthorshipsBuildQueries
    from infrastructure.pipeline.authorships.pub_counts import PgPubCountsQueries
    from pipeline.containers import (
        delete_empty_journals,
        delete_empty_monographs,
        delete_empty_publishers,
    )
    from pipeline.publications.address_pub_count import AddressPubCountQueries
    from pipeline.publications.authorships import AuthorshipsPhase
    from pipeline.publications.purge_orphan_publications import (
        PurgeOrphanPublicationsQueries,
    )

    return AuthorshipsPhase(
        PgAuthorshipsBuildQueries(),
        PurgeOrphanPublicationsQueries(),
        PgPubCountsQueries(),
        AddressPubCountQueries(),
        empty_containers=(
            (delete_empty_monographs.LIBELLE, _run_delete_empty_monographs),
            (delete_empty_journals.LIBELLE, _run_delete_empty_journals),
            (delete_empty_publishers.LIBELLE, _run_delete_empty_publishers),
        ),
    )


def _run_delete_empty_monographs() -> PhaseMetrics:
    from pipeline.containers.delete_empty_monographs import (
        run_delete_empty_monographs,
    )
    from pipeline.containers.monographs import MonographGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_monographs(log, monograph_repo=MonographGatewayQueries(conn))


def _run_delete_empty_journals() -> PhaseMetrics:
    from pipeline.containers.delete_empty_journals import (
        run_delete_empty_journals,
    )
    from pipeline.containers.journals import JournalGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_journals(log, journal_repo=JournalGatewayQueries(conn))


def _run_delete_empty_publishers() -> PhaseMetrics:
    from pipeline.containers.delete_empty_publishers import (
        run_delete_empty_publishers,
    )
    from pipeline.containers.publishers import PublisherGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_publishers(log, publisher_repo=PublisherGatewayQueries(conn))
