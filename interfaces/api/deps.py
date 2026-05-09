"""Shared dependencies: SPA static files, auth helpers, sync DB factories.

Les factories DB sync (`db_conn_sync`) sont utilisées par les routers
migrés en `def` (chantier `docs/chantiers/sync-async-deduplication.md`,
option D). Pendant la migration progressive, elles cohabitent avec les
factories async dans `interfaces/api/async_deps.py`. Phase 3 du
chantier supprimera la moitié async une fois tous les routers basculés.
"""

import hashlib
import hmac
import os
import time
from collections.abc import Iterator
from typing import Any

import bcrypt
from fastapi import Cookie, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection, text

from application.ports.admin_feedback_queries import AdminFeedbackQueries
from application.ports.config import ConfigStore
from application.ports.config_queries import ConfigQueries
from application.ports.hal_problems_queries import HalProblemsQueries
from application.ports.journals_queries import JournalQueries
from application.ports.laboratories_queries import LaboratoriesQueries
from application.ports.perimeters_queries import PerimetersAdminQueries
from application.ports.person_duplicates_queries import PersonDuplicatesQueries
from application.ports.publication_duplicates_queries import PublicationDuplicatesQueries
from application.ports.publications_queries import PublicationsQueries
from application.ports.publishers_queries import PublisherQueries
from application.ports.stats_queries import StatsQueries
from application.ports.structures_queries import StructuresQueries
from application.ports.subjects_queries import SubjectsAdminQueries
from domain.ports.audit_repository import AuditRepository
from domain.ports.authorship_repository import AuthorshipRepository
from domain.ports.journal_repository import JournalRepository
from domain.ports.perimeter_repository import PerimeterRepository
from domain.ports.person_repository import PersonRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.ports.structure_repository import StructureRepository
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queries.admin_feedback import PgAdminFeedbackQueries
from infrastructure.db.queries.config import PgConfig, PgConfigQueries
from infrastructure.db.queries.hal_problems import PgHalProblemsQueries
from infrastructure.db.queries.journals import PgJournalQueries
from infrastructure.db.queries.laboratories import PgLaboratoriesQueries
from infrastructure.db.queries.perimeter import PgPerimetersAdminQueries
from infrastructure.db.queries.person_duplicates import PgPersonDuplicatesQueries
from infrastructure.db.queries.publication_duplicates import PgPublicationDuplicatesQueries
from infrastructure.db.queries.publications import PgPublicationsQueries
from infrastructure.db.queries.publishers import PgPublisherQueries
from infrastructure.db.queries.stats import PgStatsQueries
from infrastructure.db.queries.structures import PgStructuresQueries
from infrastructure.db.queries.subjects import PgSubjectsAdminQueries
from infrastructure.repositories import (
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

    async def get_response(self, path: Any, scope: Any) -> Any:
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


def require_admin(session: str | None = Cookie(None, alias="session")) -> Any:
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
