"""Phase `affiliations` : rattachement des signatures aux structures du périmètre, par leurs adresses.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure ; `run.py` matérialise `perimeter_structures` avant toute phase. Suivent trois nœuds (`pipeline.graph`), chacun dans sa propre transaction :

1. **Référentiel ROR** (nœud `affiliations.refresh_ror`) : importe la dernière version du dump ROR si elle n'est pas déjà importée (`pipeline.transformation.structures.ror`).
2. **Résolution des adresses** (nœud `affiliations.resolve_addresses`) : rattache les adresses aux structures connues (commits par lots).
3. **Signatures du périmètre** (nœud `affiliations.populate`) : pose `in_perimeter` sur les `source_authorships` depuis les adresses résolues.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.execution import log, open_tx
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.structures.address_resolution import (
    AddressResolutionQueries,
    run_resolution,
)
from pipeline.transformation.structures.perimeter import (
    EmptyExtractionPerimeterError,
    PerimeterQueries,
)


@dataclass(frozen=True)
class AffiliationsPhase:
    address_queries: AddressResolutionQueries
    perimeter_queries: PerimeterQueries
    refresh_ror: Callable[[], PhaseMetrics]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Contrôle le périmètre d'extraction, exécute les trois nœuds et assemble les métriques de la phase."""
        with ctx.open_tx() as conn:
            if self.perimeter_queries.count_extraction_structures(conn) == 0:
                raise EmptyExtractionPerimeterError()

        by_node = run_nodes(
            "affiliations",
            {
                "affiliations.refresh_ror": NodeStep(lambda _ctx, _breaker: self.refresh_ror()),
                "affiliations.resolve_addresses": NodeStep(
                    self._resolve_addresses,
                    section="Identification des structures dans les adresses institutionnelles",
                ),
                "affiliations.populate": NodeStep(
                    self._populate, section="Rattachement des structures aux auteurs des documents"
                ),
            },
            ctx,
        )
        metrics = by_node["affiliations.resolve_addresses"]
        metrics.details.update(by_node["affiliations.refresh_ror"].details)
        metrics.resume = ""
        return metrics

    def _resolve_addresses(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            perimeter_ids = set(self.perimeter_queries.get_persons_structure_ids_list(conn))
            stats = run_resolution(conn, self.address_queries, perimeter_ids, ctx.logger)
        metrics = PhaseMetrics()
        metrics.add(total=stats.processed)
        metrics.details["summary"] = {
            "adresses": stats.processed,
            "in_perimeter": stats.in_perimeter,
        }
        return metrics

    def _populate(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            perimeter_ids = set(self.perimeter_queries.get_persons_structure_ids_list(conn))
            populate(conn, ctx.logger, perimeter_ids)
        return PhaseMetrics()


# ── Signatures du périmètre ───────────────────────────────────


class InPerimeterSyncCounts(NamedTuple):
    """Nombre de `source_authorships` dont `in_perimeter` a changé lors d'un alignement."""

    added: int  # passées à TRUE (entrées dans le périmètre)
    removed: int  # passées à FALSE (sorties du périmètre)


# Ensembles d'ids des deux UPDATE de `sync_in_perimeter` : `should` (signatures du périmètre, via la matview) et `currently` (à TRUE, via l'index partiel). Delta par EXCEPT ; un run stable produit un delta vide.
_DELTA_CTE = """
    WITH should AS (
        SELECT DISTINCT source_authorship_id AS id
        FROM source_authorship_structures
        WHERE structure_id = ANY(:perimeter_ids)
    ),
    currently AS (
        SELECT id FROM source_authorships WHERE in_perimeter
    )
"""

# Un enregistrement sans publication qui entre dans le périmètre est marqué `keys_dirty` : la phase `publications` le met alors en publication.
_ADD_SQL = text(
    _DELTA_CTE
    + """
    , entrees AS (
        UPDATE source_authorships
        SET in_perimeter = TRUE
        WHERE id IN (SELECT id FROM should EXCEPT SELECT id FROM currently)
        RETURNING source_publication_id
    ), marquees AS (
        UPDATE source_publications
        SET keys_dirty = TRUE
        WHERE id IN (SELECT source_publication_id FROM entrees)
          AND publication_id IS NULL AND NOT keys_dirty
        RETURNING 1
    )
    SELECT count(*) FROM entrees
    """
)

_REMOVE_SQL = text(
    _DELTA_CTE
    + """
    UPDATE source_authorships
    SET in_perimeter = FALSE
    WHERE id IN (SELECT id FROM currently EXCEPT SELECT id FROM should)
    """
)


def refresh_source_authorship_structures(conn: Connection) -> None:
    """Rafraîchit la matview `source_authorship_structures`, qui alimente `sync_in_perimeter`.

    À appeler après la matérialisation de `perimeter_structures` et la résolution des adresses, et avant le rafraîchissement de `authorship_structures`, qui en dérive.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_authorship_structures"))


def sync_in_perimeter(conn: Connection, *, perimeter_ids: list[int]) -> InPerimeterSyncCounts:
    """Aligne `in_perimeter` sur les structures `perimeter_ids`, lues depuis la matview, en écrivant seulement les changements.

    Un enregistrement sans publication dont une signature entre dans le périmètre est marqué `keys_dirty`.
    """
    params = {"perimeter_ids": perimeter_ids}
    added = scalar_int(conn.execute(_ADD_SQL, params))
    removed = conn.execute(_REMOVE_SQL, params).rowcount
    return InPerimeterSyncCounts(added=added, removed=removed)


def populate(conn: Connection, logger: logging.Logger, perimeter_ids: set[int]) -> None:
    """Pose `in_perimeter` sur les `source_authorships` : rafraîchit la matview `source_authorship_structures`, puis aligne `in_perimeter` sur elle. Le commit est à la charge de l'appelant."""
    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}rattachement en cours", logger) as ligne:
        refresh_source_authorship_structures(conn)
        sync_in_perimeter(conn, perimeter_ids=list(perimeter_ids))
        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rattachement des signatures aux structures du périmètre, par leurs adresses."""
    from pipeline.transformation.structures.address_resolution import (
        AddressResolutionQueries,
    )
    from pipeline.transformation.structures.perimeter import PerimeterQueries

    return AffiliationsPhase(
        AddressResolutionQueries(),
        PerimeterQueries(),
        refresh_ror=_run_refresh_ror,
    )


def _run_refresh_ror() -> PhaseMetrics:
    """Rafraîchissement du référentiel ROR depuis le dump publié sur Zenodo, sur sa propre connexion."""
    from pipeline.ingestion.http.polite_pool import build_user_agent
    from pipeline.ingestion.ror.dump import ZenodoRorDumpSource
    from pipeline.runtime.config import get_polite_pool_email_optional
    from pipeline.transformation.structures.ror import RorDumpQueries, run_refresh_ror

    # Le dump est public : l'adresse du polite pool y est facultative.
    source = ZenodoRorDumpSource(
        user_agent=build_user_agent(get_polite_pool_email_optional() or ""), logger=log
    )
    with open_tx() as conn:
        return run_refresh_ror(conn, source=source, repo=RorDumpQueries(conn), logger=log)
