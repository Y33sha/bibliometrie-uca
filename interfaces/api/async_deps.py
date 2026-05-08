"""Dépendances async FastAPI : curseur async via AsyncConnectionPool,
et câblage des adapters sortants vers leurs ports (composition root API).

`pool.connection()` gère automatiquement commit (succès) / rollback
(exception) et la restitution au pool, cf. psycopg_pool.

`get_sa_connection()` est l'équivalent SQLAlchemy : ouvre une
AsyncConnection sur l'AsyncEngine, dans une transaction commit
(succès) / rollback (exception). À utiliser par les modules migrés
en SQLAlchemy Core (chantier sqlalchemy-core-adoption). Cohabite
avec `get_async_cursor()` pendant la migration ; le pool psycopg
disparaîtra en Phase 4.

Factories `Depends(...)` (chantier routers-di) : `db_conn` ouvre une
AsyncConnection partagée par toutes les deps de la requête (FastAPI
cache les Depends par requête → même transaction). Les `*_repo`
dérivent de `db_conn`, donc plusieurs repos dans un même endpoint
partagent la transaction sans config supplémentaire.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from application.ports.addresses_queries import AsyncAddressesQueries
from application.ports.admin_feedback_queries import AsyncAdminFeedbackQueries
from application.ports.config import AsyncConfigStore
from application.ports.config_queries import AsyncConfigQueries
from application.ports.hal_problems_queries import AsyncHalProblemsQueries
from application.ports.journals_queries import AsyncJournalQueries
from application.ports.laboratories_queries import AsyncLaboratoriesQueries
from application.ports.perimeter import AsyncPerimeterQueries
from application.ports.perimeters_queries import AsyncPerimetersAdminQueries
from application.ports.person_duplicates_queries import AsyncPersonDuplicatesQueries
from application.ports.persons_queries import AsyncPersonsQueries
from application.ports.publication_duplicates_queries import AsyncPublicationDuplicatesQueries
from application.ports.publications_queries import AsyncPublicationsQueries
from application.ports.publishers_queries import AsyncPublisherQueries
from application.ports.stats_queries import AsyncStatsQueries
from application.ports.structures_queries import AsyncStructuresQueries
from application.ports.subjects_queries import AsyncSubjectsQueries
from domain.ports.address_repository import AsyncAddressRepository
from domain.ports.audit_repository import AsyncAuditRepository
from domain.ports.authorship_repository import AsyncAuthorshipRepository
from domain.ports.journal_repository import AsyncJournalRepository
from domain.ports.perimeter_repository import AsyncPerimeterRepository
from domain.ports.person_repository import AsyncPersonRepository
from domain.ports.publication_repository import AsyncPublicationRepository
from domain.ports.publisher_repository import AsyncPublisherRepository
from domain.ports.structure_repository import AsyncStructureRepository
from infrastructure.db.async_connection import get_async_pool
from infrastructure.db.engine import get_async_engine
from infrastructure.db.queries.addresses import PgAsyncAddressesQueries
from infrastructure.db.queries.admin_feedback import PgAsyncAdminFeedbackQueries
from infrastructure.db.queries.config import PgAsyncConfigQueries
from infrastructure.db.queries.hal_problems import PgAsyncHalProblemsQueries
from infrastructure.db.queries.journals import PgAsyncJournalQueries
from infrastructure.db.queries.laboratories import PgAsyncLaboratoriesQueries
from infrastructure.db.queries.perimeter import (
    PgAsyncPerimeterQueries,
    PgAsyncPerimetersAdminQueries,
)
from infrastructure.db.queries.person_duplicates import PgAsyncPersonDuplicatesQueries
from infrastructure.db.queries.persons import PgAsyncPersonsQueries
from infrastructure.db.queries.publication_duplicates import PgAsyncPublicationDuplicatesQueries
from infrastructure.db.queries.publications import PgAsyncPublicationsQueries
from infrastructure.db.queries.publishers import PgAsyncPublisherQueries
from infrastructure.db.queries.stats import PgAsyncStatsQueries
from infrastructure.db.queries.structures import PgAsyncStructuresQueries
from infrastructure.db.queries.subjects import PgAsyncSubjectsQueries
from infrastructure.repositories import (
    async_address_repository,
    async_audit_repository,
    async_authorship_repository,
    async_config_store,
    async_journal_repository,
    async_perimeter_repository,
    async_person_repository,
    async_publication_repository,
    async_publisher_repository,
    async_structure_repository,
)


@asynccontextmanager
async def get_async_cursor() -> AsyncIterator[tuple[Any, Any]]:
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            yield cur, conn


@asynccontextmanager
async def get_sa_connection() -> AsyncIterator[AsyncConnection]:
    """AsyncConnection SQLAlchemy en transaction commit/rollback auto.

    Pour les modules migrés en SQLAlchemy Core. Le `engine.begin()`
    ouvre une transaction qui commit si pas d'exception, rollback
    sinon — équivalent au pattern de `pool.connection()` côté psycopg.
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        yield conn


# ── Factories `Depends` pour les routers (chantier routers-di) ────


async def db_conn() -> AsyncIterator[AsyncConnection]:
    """AsyncConnection partagée par toutes les deps d'une même requête.

    À utiliser via `Depends(db_conn)`. Toute dépendance qui en dérive
    (`*_repo` ci-dessous) partage la même connexion → même transaction.
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        yield conn


def address_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncAddressRepository:
    return async_address_repository(conn)


def audit_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncAuditRepository:
    return async_audit_repository(conn)


def authorship_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncAuthorshipRepository:
    return async_authorship_repository(conn)


def config_store(conn: AsyncConnection = Depends(db_conn)) -> AsyncConfigStore:
    return async_config_store(conn)


def journal_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncJournalRepository:
    return async_journal_repository(conn)


def perimeter_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPerimeterRepository:
    return async_perimeter_repository(conn)


def person_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPersonRepository:
    return async_person_repository(conn)


def publication_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPublicationRepository:
    return async_publication_repository(conn)


def publisher_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPublisherRepository:
    return async_publisher_repository(conn)


def structure_repo(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncStructureRepository:
    return async_structure_repository(conn)


def publisher_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPublisherQueries:
    return PgAsyncPublisherQueries(conn)


def journal_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncJournalQueries:
    return PgAsyncJournalQueries(conn)


def laboratories_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncLaboratoriesQueries:
    return PgAsyncLaboratoriesQueries(conn)


def subjects_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncSubjectsQueries:
    return PgAsyncSubjectsQueries(conn)


def addresses_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncAddressesQueries:
    return PgAsyncAddressesQueries(conn)


def admin_feedback_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncAdminFeedbackQueries:
    return PgAsyncAdminFeedbackQueries(conn)


def hal_problems_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncHalProblemsQueries:
    return PgAsyncHalProblemsQueries(conn)


def config_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncConfigQueries:
    return PgAsyncConfigQueries(conn)


def perimeters_admin_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPerimetersAdminQueries:
    return PgAsyncPerimetersAdminQueries(conn)


def stats_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncStatsQueries:
    return PgAsyncStatsQueries(conn)


def structures_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncStructuresQueries:
    return PgAsyncStructuresQueries(conn)


def person_duplicates_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPersonDuplicatesQueries:
    return PgAsyncPersonDuplicatesQueries(conn)


def persons_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPersonsQueries:
    return PgAsyncPersonsQueries(conn)


def publication_duplicates_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPublicationDuplicatesQueries:
    return PgAsyncPublicationDuplicatesQueries(conn)


def publications_queries(
    conn: AsyncConnection = Depends(db_conn),
) -> AsyncPublicationsQueries:
    return PgAsyncPublicationsQueries(conn)


async def bg_propagate_countries(address_ids: list[int]) -> None:
    """Tâche de fond : propager les pays d'adresses → publications.

    Lancée hors cycle de requête (`BackgroundTasks`), donc les `Depends`
    ne s'appliquent pas — composition manuelle ici (composition root
    légitime).
    """
    import logging

    from application import addresses_countries as countries_service  # noqa: PLC0415

    logger = logging.getLogger(__name__)
    try:
        async with get_sa_connection() as conn:
            await countries_service.propagate_countries_to_publications(
                conn, address_ids, repo=async_address_repository(conn)
            )
    except Exception:
        logger.exception("Erreur propagation pays en background")


# ── Câblage des adapters sortants ──

# PgAsyncPerimeterQueries est sans état (le curseur est passé aux
# méthodes), donc un singleton par processus suffit. Les routers
# reçoivent l'objet via le port `AsyncPerimeterQueries` sans connaître
# l'implémentation concrète.
_perimeter_queries_singleton: AsyncPerimeterQueries = PgAsyncPerimeterQueries()


def get_perimeter_queries() -> AsyncPerimeterQueries:
    """Retourne l'implémentation enregistrée de `AsyncPerimeterQueries`."""
    return _perimeter_queries_singleton


# ----- Perimeter root -----

_root_structure_id: int | None = None


async def get_root_structure_id() -> int:
    """Retourne l'ID de la structure racine du périmètre principal.

    Lit perimeters.structure_ids[1] pour le périmètre configuré dans
    config.perimeter_persons. Valeur cachée après le premier appel
    (lookup unique par vie du processus).
    """
    global _root_structure_id
    if _root_structure_id is not None:
        return _root_structure_id
    async with get_async_cursor() as (cur, _):
        await cur.execute("""
            SELECT p.structure_ids[1] AS root_id
            FROM config c
            JOIN perimeters p ON p.code = c.value #>> '{}'
            WHERE c.key = 'perimeter_persons'
        """)
        row = await cur.fetchone()
        if row and row["root_id"]:
            _root_structure_id = row["root_id"]
        else:
            _root_structure_id = 0  # Périmètre non configuré — les filtres APC seront sans effet
    return _root_structure_id
