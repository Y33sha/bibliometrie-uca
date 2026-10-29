"""Composition root de l'API : dépendances des routers (connexion de la requête, adaptateurs de lecture, services d'écriture, utilisateur de la session) et tâches de fond.

`DbConn` fournit la connexion de la requête ; les factories construisent sur elle les adaptateurs et les services.
"""

import logging
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Connection

from application.audit_log import record_pending_events
from application.ports.repositories.user_repository import UserRepository
from application.services.addresses import AddressService
from application.services.config import ConfigService
from application.services.contributions import ContributionService
from application.services.perimeters import PerimeterService
from application.services.persons import PersonService
from application.services.publication_merge import PublicationMergeService
from application.services.publishers import PublisherService
from application.services.serials import SerialService
from application.services.structures import StructureService
from domain.merge import MergedEntity
from domain.users import Role, SessionUser
from infrastructure.db.engine import get_sync_engine
from infrastructure.read_models.addresses.queries import AddressesQueries
from infrastructure.read_models.config.queries import ConfigQueries
from infrastructure.read_models.contributions.queries import ContributionsQueries
from infrastructure.read_models.countries.queries import CountriesQueries
from infrastructure.read_models.entity_labels.queries import EntityLabelQueries
from infrastructure.read_models.feedback.queries import FeedbackQueries
from infrastructure.read_models.hal_problems.queries import HalProblemsQueries
from infrastructure.read_models.merge_redirects.queries import MergeRedirectQueries
from infrastructure.read_models.monographs.queries import MonographQueries
from infrastructure.read_models.perimeters.queries import PerimetersQueries
from infrastructure.read_models.persons.queries import PersonsQueries
from infrastructure.read_models.pipeline_runs.queries import PipelineRunsQueries
from infrastructure.read_models.publications.queries import PublicationsQueries
from infrastructure.read_models.publishers.queries import PublisherQueries
from infrastructure.read_models.serials.queries import SerialQueries
from infrastructure.read_models.stats.queries import StatsQueries
from infrastructure.read_models.structures.queries import StructuresQueries
from infrastructure.read_models.subjects.queries import SubjectsQueries
from infrastructure.repositories import (
    address_repository,
    audit_repository,
    contribution_repository,
    perimeter_repository,
    person_repository,
    publication_merge_repository,
    publisher_repository,
    serial_repository,
    structure_repository,
    user_repository,
)
from infrastructure.repositories.config_repository import PgConfigRepository
from infrastructure.settings import settings
from interfaces.api.disconnect_cancellation import request_cancellation
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.session import read_session
from pipeline.public import (
    CountryRecompute,
    PerimeterStructures,
    PublicationCountRecompute,
    PublicationPerimeterRecompute,
    PublicationRecompute,
    SerialRecompute,
    SourceContributionPerimeterRecompute,
)

logger = logging.getLogger(__name__)


# ----- Session -----


def get_admin_user() -> str:
    """Login de l'administrateur, lu dans les réglages. Exposé en dépendance : les routers n'importent pas `infrastructure`."""
    return settings.admin_user


def _session_user(token: str | None, conn: Connection) -> SessionUser | None:
    login = read_session(token) if token else None
    if login is None:
        return None
    roles = user_repository(conn).roles_of(login)
    return SessionUser(login, roles) if roles is not None else None


def load_session_user(token: str | None) -> SessionUser | None:
    """Utilisateur de la session du jeton `token`, avec ses rôles. `None` sans jeton valide, ou pour un login absent de `ops.users`.

    Ouvre sa propre connexion, en lecture seule : le middleware d'authentification l'appelle avant l'ouverture de la connexion de la requête.
    """
    with get_sync_engine().connect() as conn:
        conn.execution_options(postgresql_readonly=True)
        return _session_user(token, conn)


def ensure_admin_user() -> None:
    """Crée l'utilisateur `ADMIN_USER` avec le rôle admin s'il manque. Appelé au démarrage de l'API."""
    with get_sync_engine().begin() as conn:
        user_repository(conn).ensure_user(settings.admin_user, [Role.ADMIN])


# ----- Connexions -----


# Méthodes HTTP sans effet de bord. Starlette sert `HEAD` par la route `GET` correspondante.
READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _open_connection(request: Request) -> Connection:
    """Connexion pour la requête en cours. Toute connexion ouverte pendant une requête passe par cette fonction (`db_conn`, `connection_factory`).

    Sur une méthode de lecture, la transaction est en lecture seule (PostgreSQL refuse toute écriture), a une durée maximale par requête SQL (`api_read_statement_timeout_s`), et s'annule à la déconnexion du client (`CancelOnDisconnect`).
    """
    conn = get_sync_engine().connect()
    if request.method in READ_ONLY_METHODS:
        conn.execution_options(postgresql_readonly=True)
        conn.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{settings.api_read_statement_timeout_s}s'"
        )
        cancellation = request_cancellation(request)
        if cancellation is not None:
            cancellation.register(conn)
    return conn


def connection_factory(request: Request) -> Callable[[], Connection]:
    """Fabrique de connexions supplémentaires, avec les caractéristiques de la connexion de la requête.

    Sert les lectures parallélisées (facettes de publications). L'appelant ferme chaque connexion qu'il ouvre.
    """
    return lambda: _open_connection(request)


def db_conn(request: Request) -> Iterator[Connection]:
    """Connexion de la requête, servie aux routes par `DbConn`. Toutes les dépendances de la requête la partagent.

    Une requête d'écriture qui aboutit est commitée avec ses événements d'audit (`record_pending_events`) ; une exception l'annule. Le commit précède l'envoi de la réponse (`scope="function"`) : une requête ou une tâche de fond lancée ensuite lit l'état commité. Les services ne commitent pas.
    """
    with _open_connection(request) as conn:
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        if request.method not in READ_ONLY_METHODS:
            record_pending_events(audit_repository(conn))
            conn.commit()


# Seule déclaration de la connexion de la requête. Une déclaration d'un autre scope ouvrirait une seconde connexion, avec sa propre transaction.
DbConn = Annotated[Connection, Depends(db_conn, scope="function")]


# ----- Session, sur la connexion de la requête -----


def session_user(request: Request, conn: DbConn) -> SessionUser | None:
    """Utilisateur de la session en cours, ou `None`. Sert les lectures dont le contenu dépend de l'appelant (configuration, état de la session)."""
    return _session_user(request.cookies.get("session"), conn)


def user_repo(conn: DbConn) -> UserRepository:
    return user_repository(conn)


# ----- Lectures -----


def addresses_queries(conn: DbConn) -> AddressesQueries:
    return AddressesQueries(conn)


def config_queries(conn: DbConn) -> ConfigQueries:
    return ConfigQueries(conn)


def contributions_queries(conn: DbConn) -> ContributionsQueries:
    return ContributionsQueries(conn)


def countries_queries(conn: DbConn) -> CountriesQueries:
    return CountriesQueries(conn)


def entity_label_queries(conn: DbConn) -> EntityLabelQueries:
    return EntityLabelQueries(conn)


def entity_detail(entity: MergedEntity) -> Callable[[Request, Connection], EntityDetail]:
    """Dépendance d'une route de détail de `entity` (`interfaces.api.entity_detail`)."""

    def dependency(request: Request, conn: DbConn) -> EntityDetail:
        return EntityDetail(entity, request, MergeRedirectQueries(conn))

    return dependency


def feedback_queries(conn: DbConn) -> FeedbackQueries:
    return FeedbackQueries(conn)


def hal_problems_queries(conn: DbConn) -> HalProblemsQueries:
    return HalProblemsQueries(conn)


def monograph_queries(conn: DbConn) -> MonographQueries:
    return MonographQueries(conn)


def perimeters_queries(conn: DbConn) -> PerimetersQueries:
    return PerimetersQueries(conn)


def persons_queries(conn: DbConn) -> PersonsQueries:
    return PersonsQueries(conn)


def pipeline_runs_queries(conn: DbConn) -> PipelineRunsQueries:
    return PipelineRunsQueries(conn)


def publications_queries(
    conn: DbConn,
    open_connection: Callable[[], Connection] = Depends(connection_factory),
) -> PublicationsQueries:
    return PublicationsQueries(conn, open_connection=open_connection)


def publisher_queries(conn: DbConn) -> PublisherQueries:
    return PublisherQueries(conn)


def serial_queries(conn: DbConn) -> SerialQueries:
    return SerialQueries(conn)


def stats_queries(conn: DbConn) -> StatsQueries:
    return StatsQueries(conn)


def structures_queries(conn: DbConn) -> StructuresQueries:
    return StructuresQueries(conn)


def subjects_queries(conn: DbConn) -> SubjectsQueries:
    return SubjectsQueries(conn)


# ----- Écritures -----
# Un service par agrégat, construit sur la connexion reçue (requête, tâche de fond ou script).


def address_service(conn: DbConn) -> AddressService:
    return AddressService(
        addresses=address_repository(conn),
        contributions=contribution_repository(conn),
        country_recompute=CountryRecompute(conn),
        perimeter_structures=PerimeterStructures(conn),
        perimeter_recompute=SourceContributionPerimeterRecompute(conn),
    )


def config_service(conn: DbConn) -> ConfigService:
    return ConfigService(config=PgConfigRepository(conn))


def contribution_service(conn: DbConn) -> ContributionService:
    return ContributionService(
        persons=person_repository(conn),
        contributions=contribution_repository(conn),
        perimeter_recompute=PublicationPerimeterRecompute(conn),
    )


def perimeter_service(conn: DbConn) -> PerimeterService:
    return PerimeterService(
        perimeters=perimeter_repository(conn),
        perimeter_structures=PerimeterStructures(conn),
        config=PgConfigRepository(conn),
    )


def person_service(conn: DbConn) -> PersonService:
    return PersonService(
        persons=person_repository(conn),
        contributions=contribution_repository(conn),
        perimeter_recompute=PublicationPerimeterRecompute(conn),
    )


def publication_merge_service(conn: DbConn) -> PublicationMergeService:
    return PublicationMergeService(
        merges=publication_merge_repository(conn),
        recompute=PublicationRecompute(conn),
        perimeter_recompute=PublicationPerimeterRecompute(conn),
        conn=conn,
    )


def publisher_service(conn: DbConn) -> PublisherService:
    return PublisherService(
        publishers=publisher_repository(conn),
        serials=serial_repository(conn),
        serial_service=serial_service(conn),
        publication_count_recompute=PublicationCountRecompute(conn),
    )


def serial_service(conn: DbConn) -> SerialService:
    return SerialService(
        serials=serial_repository(conn), recompute=SerialRecompute(conn), conn=conn
    )


def structure_service(conn: DbConn) -> StructureService:
    return StructureService(
        structures=structure_repository(conn),
        perimeters=perimeter_repository(conn),
        perimeter_structures=PerimeterStructures(conn),
    )


# ----- Tâches de fond (BackgroundTasks) -----


def _run_detached(label: str, work: Callable[[Connection], None]) -> None:
    """Exécute `work` dans sa propre transaction, hors du cycle de requête, et journalise son exception éventuelle.

    Partager la connexion de la requête laisserait une transaction ouverte (idle in transaction). `work` voit les écritures de la requête, commitées avant l'envoi de la réponse.
    """
    try:
        with get_sync_engine().begin() as conn:
            work(conn)
    except Exception:
        logger.exception("Tâche de fond en échec : %s", label)


def bg_propagate_countries(address_ids: list[int]) -> None:
    """Tâche de fond : propage les pays des adresses vers les publications."""
    _run_detached(
        "propagation des pays",
        lambda conn: address_service(conn).propagate_countries_to_publications(address_ids),
    )


def bg_propagate_in_perimeter(address_ids: list[int]) -> None:
    """Tâche de fond : propage `in_perimeter` après une décision sur le lien d'une adresse à une structure. Le recalcul peut toucher des dizaines de milliers de contributions sources."""
    _run_detached(
        "propagation d'in_perimeter",
        lambda conn: address_service(conn).propagate_in_perimeter_for_addresses(address_ids),
    )
