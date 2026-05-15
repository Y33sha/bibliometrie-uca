"""Shared dependencies : SPA static files, auth helpers, DB factories.

`db_conn_sync` ouvre une `Connection` SQLAlchemy via
`engine.begin()` (commit/rollback auto) et la fournit aux routes via
`Depends(...)`. Les factories câblent les query services et
repositories sur cette Connection.
"""

import hashlib
import hmac
import os
import time
from collections.abc import Iterator

import bcrypt
from fastapi import Cookie, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection, text
from starlette.responses import Response
from starlette.types import Scope

from application.ports.api.addresses_queries import AddressesQueries
from application.ports.api.admin_feedback_queries import AdminFeedbackQueries
from application.ports.api.config_queries import ConfigQueries
from application.ports.api.hal_problems_queries import HalProblemsQueries
from application.ports.api.journals_queries import JournalQueries
from application.ports.api.laboratories_queries import LaboratoriesQueries
from application.ports.api.perimeters_queries import PerimetersAdminQueries
from application.ports.api.person_duplicates_queries import PersonDuplicatesQueries
from application.ports.api.persons_queries import PersonsQueries
from application.ports.api.publication_duplicates_queries import PublicationDuplicatesQueries
from application.ports.api.publications_queries import PublicationsQueries
from application.ports.api.publishers_queries import PublisherQueries
from application.ports.api.stats_queries import StatsQueries
from application.ports.api.structures_queries import StructuresQueries
from application.ports.api.subjects_queries import SubjectsAdminQueries
from application.ports.config import ConfigStore
from application.ports.pipeline.perimeter import PerimeterQueries
from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.person_repository import PersonRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.ports.repositories.structure_repository import StructureRepository
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.addresses import PgAddressesQueries
from infrastructure.queries.admin_feedback import PgAdminFeedbackQueries
from infrastructure.queries.config import PgConfig, PgConfigQueries
from infrastructure.queries.hal_problems import PgHalProblemsQueries
from infrastructure.queries.journals import PgJournalQueries
from infrastructure.queries.laboratories import PgLaboratoriesQueries
from infrastructure.queries.perimeter import PgPerimeterQueries, PgPerimetersAdminQueries
from infrastructure.queries.person_duplicates import PgPersonDuplicatesQueries
from infrastructure.queries.persons import PgPersonsQueries
from infrastructure.queries.publication_duplicates import PgPublicationDuplicatesQueries
from infrastructure.queries.publications import PgPublicationsQueries
from infrastructure.queries.publishers import PgPublisherQueries
from infrastructure.queries.stats import PgStatsQueries
from infrastructure.queries.structures import PgStructuresQueries
from infrastructure.queries.subjects import PgSubjectsAdminQueries
from infrastructure.repositories import (
    address_repository,
    audit_repository,
    authorship_repository,
    journal_repository,
    perimeter_repository,
    person_repository,
    publication_repository,
    publisher_repository,
    structure_repository,
)
from infrastructure.settings import settings

# ----- SPA Static Files -----

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "interfaces", "frontend", "build")


class SPAStaticFiles(StaticFiles):
    """Sert les fichiers statiques avec fallback index.html pour le routage SPA."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except Exception:
            return await super().get_response("index.html", scope)


# ----- Auth helpers -----

SESSION_MAX_AGE = 86400 * 7  # 7 jours


def _sign_token(payload: str) -> str:
    sig = hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(
        settings.session_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        parts = payload.split("|")
        ts = int(parts[1])
        if time.time() - ts > SESSION_MAX_AGE:
            return None
    except (IndexError, ValueError):
        return None
    return payload


def _check_password(password: str) -> bool:
    if not settings.admin_hash:
        return False
    return bcrypt.checkpw(password.encode(), settings.admin_hash.encode())


def get_admin_user() -> str:
    """Username admin attendu (depuis `infrastructure.settings`).

    Exposé en `Depends(...)` pour que les routers n'importent pas
    `infrastructure.settings` directement (cf. règle 4 de
    `docs/architecture.md`).
    """
    return settings.admin_user


def require_admin(session: str | None = Cookie(None, alias="session")) -> None:
    """Dépendance FastAPI : vérifie que l'utilisateur est authentifié."""
    if not session or not _verify_token(session):
        raise HTTPException(status_code=401, detail="Non authentifié")


# ----- Sync DB factories (chantier sync-async-deduplication option D) -----


def db_conn_sync() -> Iterator[Connection]:
    """Connection SA sync ouverte en transaction, pour les routers `def`.

    À utiliser via `Depends(db_conn_sync)`. Ouvre `engine.begin()` :
    commit auto en sortie sans exception, rollback sinon — équivalent
    sync de `db_conn` côté async (`interfaces/api/async_deps.py`).

    Toute dépendance qui en dérive (`*_repo` sync, query adapters
    sync) doit partager la même connexion → même transaction.
    """
    engine = get_sync_engine()
    with engine.begin() as conn:
        yield conn


def subjects_admin_queries(
    conn: Connection = Depends(db_conn_sync),
) -> SubjectsAdminQueries:
    return PgSubjectsAdminQueries(conn)


def config_queries_sync(conn: Connection = Depends(db_conn_sync)) -> ConfigQueries:
    return PgConfigQueries(conn)


def config_store_sync(conn: Connection = Depends(db_conn_sync)) -> ConfigStore:
    return PgConfig(conn)


def hal_problems_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> HalProblemsQueries:
    return PgHalProblemsQueries(conn)


def audit_repo_sync(conn: Connection = Depends(db_conn_sync)) -> AuditRepository:
    return audit_repository(conn)


def publication_repo_sync(conn: Connection = Depends(db_conn_sync)) -> PublicationRepository:
    return publication_repository(conn)


def publication_duplicates_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> PublicationDuplicatesQueries:
    return PgPublicationDuplicatesQueries(conn)


def person_repo_sync(conn: Connection = Depends(db_conn_sync)) -> PersonRepository:
    return person_repository(conn)


def person_duplicates_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> PersonDuplicatesQueries:
    return PgPersonDuplicatesQueries(conn)


def journal_queries_sync(conn: Connection = Depends(db_conn_sync)) -> JournalQueries:
    return PgJournalQueries(conn)


def journal_repo_sync(conn: Connection = Depends(db_conn_sync)) -> JournalRepository:
    return journal_repository(conn)


def publisher_queries_sync(conn: Connection = Depends(db_conn_sync)) -> PublisherQueries:
    return PgPublisherQueries(conn)


def publisher_repo_sync(conn: Connection = Depends(db_conn_sync)) -> PublisherRepository:
    return publisher_repository(conn)


def laboratories_queries_sync(conn: Connection = Depends(db_conn_sync)) -> LaboratoriesQueries:
    return PgLaboratoriesQueries(conn)


def perimeter_repo_sync(conn: Connection = Depends(db_conn_sync)) -> PerimeterRepository:
    return perimeter_repository(conn)


def perimeters_admin_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> PerimetersAdminQueries:
    return PgPerimetersAdminQueries(conn)


def admin_feedback_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> AdminFeedbackQueries:
    return PgAdminFeedbackQueries(conn)


def stats_queries_sync(conn: Connection = Depends(db_conn_sync)) -> StatsQueries:
    return PgStatsQueries(conn)


def structure_repo_sync(conn: Connection = Depends(db_conn_sync)) -> StructureRepository:
    return structure_repository(conn)


def structures_queries_sync(conn: Connection = Depends(db_conn_sync)) -> StructuresQueries:
    return PgStructuresQueries(conn)


def publications_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> PublicationsQueries:
    return PgPublicationsQueries(conn)


def authorship_repo_sync(conn: Connection = Depends(db_conn_sync)) -> AuthorshipRepository:
    return authorship_repository(conn)


def address_repo_sync(conn: Connection = Depends(db_conn_sync)) -> AddressRepository:
    return address_repository(conn)


def persons_queries_sync(conn: Connection = Depends(db_conn_sync)) -> PersonsQueries:
    return PgPersonsQueries(conn)


def addresses_queries_sync(conn: Connection = Depends(db_conn_sync)) -> AddressesQueries:
    return PgAddressesQueries(conn)


# PgPerimeterQueries est sans état (la connexion est passée aux méthodes),
# donc un singleton par processus suffit.
_perimeter_queries_sync_singleton: PerimeterQueries = PgPerimeterQueries()


def get_perimeter_queries_sync() -> PerimeterQueries:
    """Retourne le singleton sync de `PerimeterQueries`."""
    return _perimeter_queries_sync_singleton


def bg_propagate_countries_sync(address_ids: list[int]) -> None:
    """Tâche de fond sync : propager les pays d'adresses → publications.

    Lancée hors cycle de requête (`BackgroundTasks`), donc les `Depends`
    ne s'appliquent pas — composition manuelle ici (composition root).
    """
    import logging

    from application.addresses import countries as countries_service

    logger = logging.getLogger(__name__)
    try:
        engine = get_sync_engine()
        with engine.begin() as conn:
            countries_service.propagate_countries_to_publications(
                address_ids, repo=address_repository(conn)
            )
    except Exception:
        logger.exception("Erreur propagation pays en background")


# ----- Perimeter root (sync, lazy-cached) -----

_root_structure_id_sync: int | None = None


def get_root_structure_id_sync() -> int:
    """ID de la structure racine du périmètre principal (variante sync).

    Cache process-wide (lookup unique). 0 si périmètre non configuré.
    """
    global _root_structure_id_sync
    if _root_structure_id_sync is not None:
        return _root_structure_id_sync
    engine = get_sync_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT p.structure_ids[1] AS root_id
                FROM config c
                JOIN perimeters p ON p.code = c.value #>> '{}'
                WHERE c.key = 'perimeter_persons'
            """)
        ).first()
    _root_structure_id_sync = (row.root_id if row and row.root_id else 0) if row else 0
    return _root_structure_id_sync
