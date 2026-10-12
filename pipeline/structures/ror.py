"""Référentiel ROR (`ror_organizations`, `ror_relations`, `ror_dump_imports`) : import de son dump, et rafraîchissement en tête de la phase `affiliations`.

Le dump est importé seulement si sa version diffère de celle du dernier import. Un dump inaccessible laisse le référentiel en l'état.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import Connection, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, ror_relations
from infrastructure.db.tables import (
    ror_dump_imports,
    ror_organizations,
    ror_relations as ror_relations_table,
)
from pipeline.ingestion.http.dump_download import DumpUnavailableError
from pipeline.ingestion.ror.dump import ZenodoRorDumpSource
from pipeline.libelles import DERNIERE_BRANCHE, etape
from pipeline.metrics import PhaseMetrics

_BATCH_SIZE = 5000


class RorDumpQueries:
    """Accès PostgreSQL du pipeline au référentiel ROR."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace_all(
        self,
        organizations: Sequence[RorOrganization],
        relations: Iterable[tuple[RorId, RorId]],
        *,
        version: str,
    ) -> None:
        """Vide les deux tables, y écrit les organisations et les couples `(parent, enfant)`, et inscrit `version` dans `ror_dump_imports`."""
        self._conn.execute(delete(ror_relations_table))
        self._conn.execute(delete(ror_organizations))
        for batch in batched(organizations, _BATCH_SIZE):
            self._conn.execute(
                insert(ror_organizations),
                [
                    {
                        "ror_id": org.ror_id.value,
                        "name": org.name,
                        "country_code": org.country_code,
                        "types": sorted(org.types),
                        "status": org.status.value,
                    }
                    for org in batch
                ],
            )
        for relation_batch in batched(relations, _BATCH_SIZE):
            self._conn.execute(
                insert(ror_relations_table),
                [
                    {"parent_ror_id": parent.value, "child_ror_id": child.value}
                    for parent, child in relation_batch
                ],
            )
        self._conn.execute(
            pg_insert(ror_dump_imports)
            .values(version=version, imported_at=func.clock_timestamp())
            .on_conflict_do_update(
                index_elements=["version"], set_={"imported_at": func.clock_timestamp()}
            )
        )

    def last_imported_version(self) -> str | None:
        """Version du dernier import, `None` sans import."""
        return self._conn.execute(
            select(ror_dump_imports.c.version)
            .order_by(ror_dump_imports.c.imported_at.desc())
            .limit(1)
        ).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class RorImportStats:
    organizations: int
    relations: int


def import_ror_dump(
    conn: Connection,
    organizations: Iterable[RorOrganization],
    *,
    version: str,
    repo: RorDumpQueries,
) -> RorImportStats:
    """Remplit le référentiel ROR avec les organisations du dump `version` et leurs relations parent/enfant, en une transaction."""
    orgs = list(organizations)
    relations = ror_relations(orgs)
    repo.replace_all(orgs, relations, version=version)
    conn.commit()
    return RorImportStats(organizations=len(orgs), relations=len(relations))


def run_refresh_ror(
    conn: Connection,
    *,
    source: ZenodoRorDumpSource,
    repo: RorDumpQueries,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Importe la dernière version du dump ROR si elle n'est pas déjà importée."""
    metrics = PhaseMetrics()
    etape(logger, "Référentiel ROR")
    try:
        latest = source.latest_version()
        if latest == repo.last_imported_version():
            logger.info("%sVersion %s déjà importée", DERNIERE_BRANCHE, latest)
            metrics.details["ror"] = {"version": latest, "imported": False}
            return metrics
        stats = import_ror_dump(conn, source.organizations(latest), version=latest, repo=repo)
    except DumpUnavailableError as e:
        conn.rollback()
        logger.warning("%sDump ROR inaccessible, référentiel inchangé : %s", DERNIERE_BRANCHE, e)
        metrics.details["ror"] = {"imported": False, "error": str(e)}
        return metrics
    logger.info(
        "%sVersion %s importée : %d organisations, %d relations",
        DERNIERE_BRANCHE,
        latest,
        stats.organizations,
        stats.relations,
    )
    metrics.details["ror"] = {"version": latest, "imported": True}
    return metrics
