"""Référentiel ROR (`ror_organizations`, `ror_relations`, `ror_dump_imports`) : import de son dump, et rafraîchissement en tête de la phase `affiliations`.

Le dump est importé seulement si sa version diffère de celle du dernier import. La version publiée se lit d'abord chez DataCite : Zenodo est interrogé seulement quand elle diffère, ou quand DataCite ne répond pas. Un dump inaccessible laisse le référentiel en l'état.

Quand une organisation change de pays, l'import marque les contributions sources qui la citent sans adresse, pour la phase `countries`.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import Connection, delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, ror_relations
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.db.tables import (
    ror_dump_imports,
    ror_organizations,
    ror_relations as ror_relations_table,
)
from pipeline.http.dump_download import DumpUnavailableError
from pipeline.ingestion.complements.ror import ZenodoRorDumpSource, dump_version
from pipeline.runtime.observability.log_format import LAST_BRANCH, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unavailable

_BATCH_SIZE = 5000


class RorStore:
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
        """Vide les deux tables, y écrit les organisations et les couples `(parent, enfant)`, et inscrit `version` dans `ror_dump_imports`. Marque les dépendants des organisations dont le pays change (`_mark_country_changes`)."""
        previous = dict(
            self._conn.execute(
                select(ror_organizations.c.ror_id, ror_organizations.c.country_code)
            ).all()
        )
        self._conn.execute(delete(ror_relations_table))
        self._conn.execute(delete(ror_organizations))
        for batch in batched(organizations, _BATCH_SIZE, strict=False):
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
        for relation_batch in batched(relations, _BATCH_SIZE, strict=False):
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
        current = {org.ror_id.value: org.country_code for org in organizations}
        self._mark_country_changes(
            [
                ror_id
                for ror_id in previous.keys() | current.keys()
                if previous.get(ror_id) != current.get(ror_id)
            ]
        )

    def _mark_country_changes(self, ror_ids: list[str]) -> None:
        """Pour les organisations `ror_ids` : marque pour le recalcul des pays les contributions sources qui les citent sans adresse."""
        if not ror_ids:
            return
        self._conn.execute(
            text(
                enqueue_sql(
                    Queue.SOURCE_CONTRIBUTION_COUNTRIES,
                    """
                    SELECT source_contribution_id FROM source_contribution_rors
                    WHERE ror_id = ANY(:ids) AND address_id IS NULL
                    """,
                )
            ),
            {"ids": ror_ids},
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
    store: RorStore,
) -> RorImportStats:
    """Remplit le référentiel ROR avec les organisations du dump `version` et leurs relations parent/enfant, en une transaction."""
    orgs = list(organizations)
    relations = ror_relations(orgs)
    store.replace_all(orgs, relations, version=version)
    conn.commit()
    return RorImportStats(organizations=len(orgs), relations=len(relations))


def run_refresh_ror(
    conn: Connection,
    *,
    source: ZenodoRorDumpSource,
    store: RorStore,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Importe la dernière version du dump ROR si elle n'est pas déjà importée."""
    metrics = PhaseMetrics()
    step(logger, "Référentiel ROR")
    last = store.last_imported_version()
    published = source.published_version()
    if last and published and dump_version(last) == published:
        logger.info("%sVersion %s déjà importée", LAST_BRANCH, last)
        metrics.details["ror"] = {"version": last, "imported": False}
        return metrics
    try:
        latest = source.latest_version()
        if latest == last:
            logger.info("%sVersion %s déjà importée", LAST_BRANCH, latest)
            metrics.details["ror"] = {"version": latest, "imported": False}
            return metrics
        stats = import_ror_dump(conn, source.organizations(latest), version=latest, store=store)
    except DumpUnavailableError as e:
        conn.rollback()
        logger.warning("%sDump ROR inaccessible, référentiel inchangé : %s", LAST_BRANCH, e)
        signal_source_unavailable(metrics, "ROR", logger=logger, phase="affiliations")
        metrics.details["ror"] = {"imported": False, "error": str(e)}
        metrics.report = "dump ROR inaccessible, import repris au prochain run"
        return metrics
    logger.info(
        "%sVersion %s importée : %d organisations, %d relations",
        LAST_BRANCH,
        latest,
        stats.organizations,
        stats.relations,
    )
    metrics.details["ror"] = {"version": latest, "imported": True}
    return metrics
