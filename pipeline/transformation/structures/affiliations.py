"""Phase `affiliations` : rattachement des signatures aux structures du périmètre, par leurs adresses.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure ; `run.py` matérialise `perimeter_structures` avant toute phase. Suivent trois nœuds (`pipeline.graph`), chacun dans sa propre transaction :

1. **Référentiel ROR** (nœud `affiliations.refresh_ror`) : importe la dernière version du dump ROR si elle n'est pas déjà importée (`pipeline.transformation.structures.ror`).
2. **Résolution des adresses** (nœud `affiliations.resolve_addresses`) : rattache les adresses aux structures connues (commits par lots).
3. **Signatures du périmètre** (nœud `affiliations.populate`) : pose les indices de l'entrée dans le périmètre (`perimeter_evidence`) sur les `source_authorships`, d'après les adresses résolues et l'identité des personnes RH.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import NO_PERIMETER_EVIDENCE, signature_perimeter_evidence
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
    """Nombre de `source_authorships` entrées dans le périmètre et sorties du périmètre lors d'une synchronisation."""

    added: int
    removed: int


def _sync_sql(scoped: bool) -> str:
    """Synchronisation de `perimeter_evidence` sur les indices calculés, restreinte aux signatures `:signature_ids` quand `scoped` est vrai.

    Seules les signatures dont les indices changent sont écrites. Un enregistrement sans publication dont une signature entre dans le périmètre est marqué `keys_dirty` : la phase `publications` le met alors en publication.
    """
    scope = "AND sa.id = ANY(:signature_ids)" if scoped else ""
    return f"""
        WITH computed AS (
            {signature_perimeter_evidence("signature_ids" if scoped else None)}
        ), target AS (
            SELECT id, evidence FROM computed
            UNION ALL
            SELECT sa.id, {NO_PERIMETER_EVIDENCE}
            FROM source_authorships sa
            LEFT JOIN computed c ON c.id = sa.id
            WHERE sa.in_perimeter AND c.id IS NULL {scope}
        ), changed AS (
            UPDATE source_authorships sa
            SET perimeter_evidence = t.evidence
            FROM target t
            WHERE sa.id = t.id AND sa.perimeter_evidence IS DISTINCT FROM t.evidence
            RETURNING sa.source_publication_id, old.in_perimeter AS was_in, new.in_perimeter AS is_in
        ), marked AS (
            UPDATE source_publications
            SET keys_dirty = TRUE
            WHERE id IN (SELECT source_publication_id FROM changed WHERE is_in AND NOT was_in)
              AND publication_id IS NULL AND NOT keys_dirty
            RETURNING 1
        )
        SELECT count(*) FILTER (WHERE is_in AND NOT was_in) AS added,
               count(*) FILTER (WHERE was_in AND NOT is_in) AS removed
        FROM changed
    """


_SYNC_ALL = text(_sync_sql(scoped=False))
_SYNC_SCOPED = text(_sync_sql(scoped=True))


def refresh_source_authorship_structures(conn: Connection) -> None:
    """Rafraîchit la matview `source_authorship_structures`, qui alimente `sync_perimeter_evidence`.

    À appeler après la matérialisation de `perimeter_structures` et la résolution des adresses, et avant le rafraîchissement de `authorship_structures`, qui en dérive.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_authorship_structures"))


def sync_perimeter_evidence(
    conn: Connection, *, perimeter_ids: list[int], signature_ids: list[int] | None = None
) -> InPerimeterSyncCounts:
    """Aligne `source_authorships.perimeter_evidence` sur les indices calculés (`signature_perimeter_evidence`), pour toutes les signatures ou pour `signature_ids`."""
    if signature_ids is None:
        row = conn.execute(_SYNC_ALL, {"perimeter_ids": perimeter_ids}).one()
    else:
        row = conn.execute(
            _SYNC_SCOPED, {"perimeter_ids": perimeter_ids, "signature_ids": signature_ids}
        ).one()
    return InPerimeterSyncCounts(added=row.added, removed=row.removed)


def populate(conn: Connection, logger: logging.Logger, perimeter_ids: set[int]) -> None:
    """Pose les indices de l'entrée dans le périmètre sur les `source_authorships` : rafraîchit la matview `source_authorship_structures`, puis synchronise `perimeter_evidence`. Le commit est à la charge de l'appelant."""
    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}rattachement en cours", logger) as ligne:
        refresh_source_authorship_structures(conn)
        sync_perimeter_evidence(conn, perimeter_ids=list(perimeter_ids))
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
