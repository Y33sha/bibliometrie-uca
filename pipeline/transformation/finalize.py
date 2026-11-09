"""Phase `finalize` : données dérivées des contributions, après la résolution des personnes. Chaque tâche a sa transaction.

La phase supprime les publications sans enregistrement source, ou sans contribution rattachée à une personne ni indice d'appartenance au périmètre lié au document (`DOCUMENT_EVIDENCE`). Elle recompose ensuite le périmètre des publications et les vues matérialisées des structures, sur les publications restantes. Elle recalcule l'éditeur des revues, supprime les référentiels vides, puis recompte les publications des adresses, revues et éditeurs.

Les référentiels vides se suppriment dans l'ordre monographies, revues, éditeurs : une monographie retient sa collection, une revue ou un préfixe DOI son éditeur. Leur suppression suit celle des publications : un référentiel vidé pendant le run disparaît dans le même run.

La phase traite toutes les sources et ignore `--sources` : une contribution change aussi hors de la normalisation, par les affiliations ou le recalcul d'une publication.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from pipeline.graph import Step, Task, in_transaction
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.publications.lifecycle import purge_publications
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)
from pipeline.transformation.publishing.monographs import delete_empty_monographs
from pipeline.transformation.publishing.publication_counts import (
    refresh_publisher_publication_counts,
    refresh_serial_publication_counts,
)
from pipeline.transformation.publishing.publishers import delete_empty_publishers
from pipeline.transformation.publishing.serials import delete_empty_serials
from pipeline.transformation.publishing.serials.serial_publishers import (
    refresh_serial_publishers,
)
from pipeline.transformation.structures.address_publication_count import (
    recompute_address_publication_count,
)

_PURGE_BATCH_SIZE = 5000
_SYNC_SECTION = "Synchronisation des tables"
_EMPTY_CONTAINERS_SECTION = "Référentiels vides"


def count_contributions_in_perimeter(conn: Connection) -> int:
    """Renvoie le nombre de contributions du périmètre rattachées à une personne."""
    return scalar_int(
        conn.execute(
            text("SELECT COUNT(*) FROM contributions WHERE person_id IS NOT NULL AND in_perimeter")
        )
    )


def refresh_contribution_structures(conn: Connection) -> None:
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY contribution_structures"))


def refresh_publication_structures(conn: Connection) -> None:
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_structures"))


def refresh_publication_rors(conn: Connection) -> None:
    """Rafraîchit les ROR des auteurs de chaque publication, ancêtres compris. Lit `publication_structures`, rafraîchie avant."""
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_rors"))


def _purge(ctx: PhaseContext) -> PhaseMetrics:
    """Purge les publications par lots, un commit par lot."""
    purged = 0
    with ctx.open_tx() as conn:
        while deleted := purge_publications(conn, limit=_PURGE_BATCH_SIZE):
            conn.commit()
            purged += deleted
    metrics = PhaseMetrics()
    metrics.details["purged"] = purged
    if purged:
        metrics.report = quantity(purged, "publication supprimée", "publications supprimées")
    return metrics


def _publications_in_perimeter(ctx: PhaseContext) -> PhaseMetrics:
    t0 = time.perf_counter()
    with ctx.open_tx() as conn:
        refresh_publications_perimeter_evidence(conn)
        in_perimeter = count_contributions_in_perimeter(conn)
    metrics = _timed(t0)
    metrics.details["in_perimeter"] = in_perimeter
    return metrics


def _structures(ctx: PhaseContext) -> PhaseMetrics:
    t0 = time.perf_counter()
    with ctx.open_tx() as conn:
        refresh_contribution_structures(conn)
        refresh_publication_structures(conn)
        refresh_publication_rors(conn)
    return _timed(t0)


def _serial_publishers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        changed = refresh_serial_publishers(conn)
    metrics = PhaseMetrics()
    metrics.report = (
        f"{quantity(changed, 'revue')} {inflect(changed, 'mise à jour', 'mises à jour')}"
    )
    return metrics


def _timed(t0: float) -> PhaseMetrics:
    """Renvoie les métriques d'une tâche de synchronisation, avec sa durée pour bilan."""
    metrics = PhaseMetrics()
    metrics.report = f"{time.perf_counter() - t0:.1f}s"
    return metrics


def _publication_counts(ctx: PhaseContext) -> PhaseMetrics:
    """Recalcule le nombre de publications de chaque adresse, revue et éditeur.

    Les trois décomptes lisent les mêmes publications et contributions sources, stables à ce point du pipeline.

    Chaque décompte est long : sa ligne annonce le travail en cours, puis affiche son résultat.
    """
    step(ctx.logger, "Recalcul des décomptes de publications")

    with waiting(f"{BRANCH}par adresse", ctx.logger) as line:
        with ctx.open_tx() as conn:
            addresses = recompute_address_publication_count(conn)
        line.conclude(
            f"{BRANCH}{quantity(addresses, 'adresse')} {inflect(addresses, 'mise à jour', 'mises à jour')}"
        )

    with waiting(f"{BRANCH}par revue", ctx.logger) as line:
        with ctx.open_tx() as conn:
            serials = refresh_serial_publication_counts(conn)
        line.conclude(
            f"{BRANCH}{quantity(serials, 'revue')} {inflect(serials, 'mise à jour', 'mises à jour')}"
        )

    with waiting(f"{LAST_BRANCH}par éditeur", ctx.logger) as line:
        with ctx.open_tx() as conn:
            publishers = refresh_publisher_publication_counts(conn)
        # « mis à jour » ne varie pas au pluriel, contrairement à « mise à jour ».
        line.conclude(f"{LAST_BRANCH}{quantity(publishers, 'éditeur')} mis à jour")

    return PhaseMetrics()


_PURGE_PUBLICATIONS = Task(
    "purge_publications",
    reads=(
        "publications.id",
        "source_records.publication_id",
        "contributions.id",
        "contributions.publication_id",
        "contributions.person_id",
        "source_contributions.perimeter_evidence",
    ),
    # La suppression d'une publication emporte ses contributions, leurs alignements, ses relations, ses sujets et son détail. Elle détache ses enregistrements sources et ses paiements APC.
    writes=(
        "publications.id",
        "contributions.id",
        "aligned_source_contributions",
        "contribution_resolution_queue",
        "publication_relations",
        "publication_subjects",
        "publications_detail",
        "source_records.publication_id",
        "apc_payments.publication_id",
    ),
    run=_purge,
    section=_SYNC_SECTION,
    label="Purge des publications",
)


_PUBLICATIONS_IN_PERIMETER = Task(
    "publications_in_perimeter",
    reads=(
        "contributions.person_id",
        "contributions.perimeter_evidence",
        "contributions.roles",
        "persons.exclusion",
        "publications.id",
        "source_records.publication_id",
        "source_contributions.perimeter_evidence",
    ),
    writes=("publications.in_perimeter",),
    run=_publications_in_perimeter,
    section=_SYNC_SECTION,
    label="Périmètre des publications",
)


_STRUCTURES = Task(
    "structures",
    reads=(
        "source_contribution_structures",
        "contributions.id",
        "contributions.publication_id",
        "contributions.person_id",
        "contributions.roles",
        "aligned_source_contributions",
        "persons.exclusion",
        "source_contribution_rors",
        "ror_relations",
        "structures.ror_id",
    ),
    writes=("contribution_structures", "publication_structures", "publication_rors"),
    run=_structures,
    section=_SYNC_SECTION,
    label="Structures des liens",
)


_SERIAL_PUBLISHERS = Task(
    "serial_publishers",
    reads=(
        "serials.id",
        "publications.serial_id",
        "publications.monograph_id",
        "publications.publisher_id",
        "publications.publication_year",
        "monographs.serial_id",
    ),
    writes=("serials.publisher_id",),
    # Les revues et les monographies supprimées ensuite comme référentiels vides n'ont pas de publication : leur suppression ne change aucun éditeur.
    previous_run=("serials.id", "monographs.serial_id"),
    run=_serial_publishers,
    section=_SYNC_SECTION,
    label="Éditeur des revues",
)


_DELETE_EMPTY_MONOGRAPHS = Task(
    "delete_empty_monographs",
    reads=(
        "monographs.id",
        "monographs.title",
        "source_records.monograph_id",
        "publications.monograph_id",
    ),
    writes=("monographs.id",),
    run=in_transaction(delete_empty_monographs.run_delete_empty_monographs),
    section=_EMPTY_CONTAINERS_SECTION,
    label=delete_empty_monographs.LABEL,
)


_DELETE_EMPTY_SERIALS = Task(
    "delete_empty_serials",
    reads=(
        "serials.id",
        "serials.title",
        "serials.publisher_id",
        # Nom de l'éditeur de chaque revue supprimée, pour le journal.
        "publishers.name",
        "source_records.serial_id",
        "publications.serial_id",
        "apc_payments.serial_id",
        "monographs.serial_id",
        # ISSN cités par la série d'un enregistrement source, ou reliés à un autre titre.
        "serial_issns",
        "source_records.biblio",
        "issn_links",
    ),
    # La suppression d'une revue emporte ses espaces de noms DOI et ses décisions de titre. Elle détache ses ISSN.
    writes=(
        "serials.id",
        "serial_doi_namespaces",
        "serial_title_decisions",
        "serial_issns.serial_id",
    ),
    # Les éditeurs supprimés ensuite comme référentiels vides sont sans revue.
    previous_run=("publishers.name",),
    run=in_transaction(delete_empty_serials.run_delete_empty_serials),
    section=_EMPTY_CONTAINERS_SECTION,
    label=delete_empty_serials.LABEL,
)


_DELETE_EMPTY_PUBLISHERS = Task(
    "delete_empty_publishers",
    reads=(
        "publishers.id",
        "publishers.name",
        "serials.publisher_id",
        "monographs.publisher_id",
        "doi_prefixes.publisher_id",
        "apc_payments.publisher_id",
        "source_records.publisher_id",
        "publications.publisher_id",
    ),
    # La suppression d'un éditeur emporte ses formes de nom.
    writes=("publishers.id", "publisher_name_forms"),
    run=in_transaction(delete_empty_publishers.run_delete_empty_publishers),
    section=_EMPTY_CONTAINERS_SECTION,
    label=delete_empty_publishers.LABEL,
)


_PUBLICATION_COUNTS = Task(
    "publication_counts",
    reads=(
        "addresses.id",
        "source_contribution_addresses",
        "source_contributions.source_record_id",
        "source_records.publication_id",
        "source_records.serial_id",
        "serials.id",
        "publishers.id",
        "publications.id",
        "publications.in_perimeter",
        "publications.serial_id",
        "publications.publisher_id",
    ),
    writes=(
        "addresses.publication_count",
        "serials.publication_count",
        "publishers.publication_count",
    ),
    previous_run=("addresses",),
    run=_publication_counts,
)


STEPS = (
    _PURGE_PUBLICATIONS,
    _PUBLICATIONS_IN_PERIMETER,
    _STRUCTURES,
    Step(
        "publishing_referentials",
        "publications → éditeur de chaque revue, référentiels de l'édition sans entrée vide",
        (
            _SERIAL_PUBLISHERS,
            _DELETE_EMPTY_MONOGRAPHS,
            _DELETE_EMPTY_SERIALS,
            _DELETE_EMPTY_PUBLISHERS,
        ),
    ),
    _PUBLICATION_COUNTS,
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : celles des suppressions de référentiels vides, et un résumé."""
    metrics = PhaseMetrics()
    for name in ("delete_empty_monographs", "delete_empty_serials", "delete_empty_publishers"):
        metrics.merge(by_task[name])
    metrics.details["summary"] = {
        "total_in_perimeter": by_task["publications_in_perimeter"].details["in_perimeter"],
        "publications_purged": by_task["purge_publications"].details["purged"],
    }
    return metrics
