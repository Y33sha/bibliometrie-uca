"""Dépendances partagées des routers : helpers d'authentification, factories DB, tâches de fond.

`db_conn_sync` fournit aux routes, par `Depends(...)`, la connexion sur laquelle les factories câblent les query services et les repositories.
"""

import hashlib
import hmac
import logging
import time
from collections.abc import Callable, Iterator

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy import Connection

from application.ports.api.addresses_queries import AddressesQueries
from application.ports.api.admin_feedback_queries import AdminFeedbackQueries
from application.ports.api.config_queries import ConfigQueries
from application.ports.api.hal_problems_queries import HalProblemsQueries
from application.ports.api.journals_queries import JournalQueries
from application.ports.api.laboratories_queries import LaboratoriesQueries
from application.ports.api.perimeters_queries import PerimetersAdminQueries
from application.ports.api.persons_queries import PersonsQueries
from application.ports.api.pipeline_phase_executions_queries import PhaseExecutionsQueries
from application.ports.api.publication_duplicates_queries import PublicationDuplicatesQueries
from application.ports.api.publications_queries import PublicationsQueries
from application.ports.api.publishers_queries import PublisherQueries
from application.ports.api.stats_queries import StatsQueries
from application.ports.api.structures_queries import StructuresQueries
from application.ports.api.subjects_queries import SubjectsAdminQueries
from application.ports.config import ConfigStore
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
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
from application.services.addresses import countries as countries_service
from application.services.authorships.core import propagate_in_perimeter_for_addresses
from infrastructure.db.dml_guard import has_uncommitted_dml, reset_dml_flag
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.api.addresses import PgAddressesQueries
from infrastructure.queries.api.admin_feedback import PgAdminFeedbackQueries
from infrastructure.queries.api.hal_problems import PgHalProblemsQueries
from infrastructure.queries.api.journals import PgJournalQueries
from infrastructure.queries.api.laboratories import PgLaboratoriesQueries
from infrastructure.queries.api.persons import PgPersonsQueries
from infrastructure.queries.api.pipeline_phase_executions import PgPhaseExecutionsQueries
from infrastructure.queries.api.publication_duplicates import PgPublicationDuplicatesQueries
from infrastructure.queries.api.publications import PgPublicationsQueries
from infrastructure.queries.api.publishers import PgPublisherQueries
from infrastructure.queries.api.stats import PgStatsQueries
from infrastructure.queries.api.structures import PgStructuresQueries
from infrastructure.queries.config import PgConfig, PgConfigQueries
from infrastructure.queries.perimeter import PgPerimeterQueries, PgPerimetersAdminQueries
from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries
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

logger = logging.getLogger(__name__)


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

    Exposé en `Depends(...)` pour que les routers n'importent pas `infrastructure.settings` directement (règle 4 de `docs/architecture/01-vue-d-ensemble.md`, tenue par un contrat import-linter).
    """
    return settings.admin_user


def require_admin(session: str | None = Cookie(None, alias="session")) -> None:
    """Dépendance FastAPI : vérifie que l'utilisateur est authentifié."""
    if not session or not _verify_token(session):
        raise HTTPException(status_code=401, detail="Non authentifié")


# ----- Factories DB sync -----


def db_conn_sync(request: Request) -> Iterator[Connection]:
    """Connection SQLAlchemy sync ouverte pour les routers `def`, via `Depends(db_conn_sync)`.

    La persistance est la prérogative du use case : un command handler de la couche application appelle `conn.commit()` lui-même avant de retourner, ce qui persiste la donnée *avant* l'envoi de la réponse. FastAPI exécute le teardown des dépendances `yield` après cet envoi : un commit placé ici arriverait trop tard, et un GET ou une tâche de fond déclenchés dans l'intervalle liraient l'état antérieur.

    En sortie, la transaction est **annulée** (`rollback`) : une session de lecture, ou une session dont le command handler a committé, n'a rien à persister. Du DML qui atteint cette sortie sans commit signale une écriture qui contourne les command handlers : le rollback la perd, et un warning la signale. Toute dépendance qui en dérive (repositories et query adapters sync) partage la même connexion.
    """
    engine = get_sync_engine()
    with engine.connect() as conn:
        reset_dml_flag(conn)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        if conn.in_transaction():
            escaped_dml = has_uncommitted_dml(conn)
            conn.rollback()
            if escaped_dml:
                logger.warning(
                    "DML annulé : %s %s a émis une écriture qui n'est pas passée par un "
                    "command handler committant ; le rollback de fin de db_conn_sync l'a perdue.",
                    request.method,
                    request.url.path,
                )


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


def pipeline_phase_executions_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> PhaseExecutionsQueries:
    return PgPhaseExecutionsQueries(conn)


def addresses_queries_sync(conn: Connection = Depends(db_conn_sync)) -> AddressesQueries:
    return PgAddressesQueries(conn)


# `PgPerimeterQueries` est sans état (la connexion est passée aux méthodes) : un singleton par processus suffit.
_perimeter_queries_singleton: PerimeterQueries = PgPerimeterQueries()


def get_perimeter_queries_sync() -> PerimeterQueries:
    return _perimeter_queries_singleton


def get_apc_structure_ids_sync(
    conn: Connection = Depends(db_conn_sync),
    perimeter_queries: PerimeterQueries = Depends(get_perimeter_queries_sync),
) -> list[int]:
    """Structures considérées comme « internes » pour la catégorisation APC.

    Réutilise le périmètre `perimeter_persons`, avec expansion `est_tutelle_de` : l'établissement et tous ses laboratoires. Une publication APC est classée interne dès qu'un de ses `apc_payments.budget_structure_id` appartient à cet ensemble.

    Pas de cache applicatif : la lecture est un lookup par clé primaire, que FastAPI résout une fois par requête, et l'invalidation reste transparente quand le périmètre change via `/admin/config` ou que ses structures évoluent.
    """
    return perimeter_queries.get_persons_structure_ids_list(conn)


# `PgMetadataCorrectionQueries` est sans état (la connexion est passée aux méthodes) : un singleton par processus suffit.
_metadata_correction_queries_singleton: MetadataCorrectionQueries = PgMetadataCorrectionQueries()


def metadata_correction_queries_sync() -> MetadataCorrectionQueries:
    """Corrections de métadonnées déclenchées par les hooks d'édition des revues."""
    return _metadata_correction_queries_singleton


# ----- Tâches de fond (BackgroundTasks) -----


def _run_detached(label: str, work: Callable[[Connection], None]) -> None:
    """Exécute `work` sur une connexion à elle, hors du cycle de requête.

    Une tâche de fond s'exécute pendant l'envoi de la réponse, en parallèle de la requête qui l'a enregistrée : la connexion de celle-ci appartient à un autre contexte, et la partager laisserait une transaction ouverte (idle in transaction). `engine.begin()` commite en sortie, annule sur exception, et ferme dans les deux cas.

    L'exception est piégée et loguée : une tâche de fond n'a personne à qui la remonter, la réponse étant partie. `work` voit les écritures que le command handler de la requête a committées avant de retourner.
    """
    try:
        with get_sync_engine().begin() as conn:
            work(conn)
    except Exception:
        logger.exception("Tâche de fond en échec : %s", label)


def bg_propagate_countries_sync(address_ids: list[int]) -> None:
    """Tâche de fond : propage les pays des adresses vers les publications."""
    _run_detached(
        "propagation des pays",
        lambda conn: countries_service.propagate_countries_to_publications(
            address_ids, repo=address_repository(conn)
        ),
    )


def bg_propagate_in_perimeter_sync(address_ids: list[int]) -> None:
    """Tâche de fond : propage `in_perimeter` après une review d'affiliation.

    Le recalcul peut toucher des dizaines de milliers de `source_authorships`, d'où son décorrélage de la réponse admin.
    """
    _run_detached(
        "propagation d'in_perimeter",
        lambda conn: propagate_in_perimeter_for_addresses(
            conn,
            address_ids,
            repo=authorship_repository(conn),
            perimeter_queries=get_perimeter_queries_sync(),
        ),
    )
