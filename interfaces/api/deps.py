"""Dépendances partagées des routers : factories DB, tâches de fond, réglages du serveur.

`DbConn` fournit aux routes la connexion de la requête, sur laquelle les factories construisent les adaptateurs de lecture et les services d'écriture.

Le jeton de session appartient à `session.py` ; ce module en tire l'utilisateur et ses rôles, lus dans `ops.users`.
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
from application.services.publishers import PublisherService
from application.services.serials import SerialService
from application.services.structures import StructureService
from domain.merge import MergedEntity
from domain.users import Role, SessionUser
from infrastructure.db.engine import get_sync_engine
from infrastructure.read_models.addresses import AddressesQueries
from infrastructure.read_models.config import ConfigQueries
from infrastructure.read_models.contributions import ContributionsQueries
from infrastructure.read_models.countries import CountriesQueries
from infrastructure.read_models.entity_labels import EntityLabelQueries
from infrastructure.read_models.feedback import FeedbackQueries
from infrastructure.read_models.hal_problems import HalProblemsQueries
from infrastructure.read_models.merge_redirects import MergeRedirectQueries
from infrastructure.read_models.monographs import MonographQueries
from infrastructure.read_models.perimeters import PerimetersQueries
from infrastructure.read_models.persons import PersonsQueries
from infrastructure.read_models.pipeline_runs import PipelineRunsQueries
from infrastructure.read_models.publications import PublicationsQueries
from infrastructure.read_models.publishers import PublisherQueries
from infrastructure.read_models.serials import SerialQueries
from infrastructure.read_models.stats import StatsQueries
from infrastructure.read_models.structures import StructuresQueries
from infrastructure.read_models.subjects import SubjectsQueries
from infrastructure.repositories import (
    address_repository,
    audit_repository,
    contribution_repository,
    perimeter_repository,
    person_repository,
    publisher_repository,
    serial_repository,
    structure_repository,
    user_repository,
)
from infrastructure.repositories.config_repository import PgConfigRepository
from infrastructure.settings import settings
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.session import read_session
from pipeline.public import (
    CountryRecompute,
    PerimeterStructures,
    PublicationCountRecompute,
    PublicationPerimeterRecompute,
    SerialRecompute,
    SourceContributionPerimeterRecompute,
)

logger = logging.getLogger(__name__)


# ----- Session -----


def get_admin_user() -> str:
    """Username admin attendu (depuis `infrastructure.settings`).

    Exposé en `Depends(...)` pour que les routers n'importent pas `infrastructure.settings` directement (tenu par un contrat import-linter).
    """
    return settings.admin_user


def _session_user(token: str | None, conn: Connection) -> SessionUser | None:
    login = read_session(token) if token else None
    if login is None:
        return None
    roles = user_repository(conn).roles_of(login)
    return SessionUser(login, roles) if roles is not None else None


def load_session_user(token: str | None) -> SessionUser | None:
    """Utilisateur de la session portée par `token`, avec ses rôles. `None` sans jeton valide, ou pour un login absent de `ops.users`.

    Ouvre sa propre connexion, en lecture seule : le middleware des écritures l'appelle avant que la requête ait la sienne.
    """
    with get_sync_engine().connect() as conn:
        conn.execution_options(postgresql_readonly=True)
        return _session_user(token, conn)


def ensure_admin_user() -> None:
    """Crée l'utilisateur `ADMIN_USER` avec le rôle admin s'il manque. Appelé au démarrage de l'API."""
    with get_sync_engine().begin() as conn:
        user_repository(conn).ensure_user(settings.admin_user, [Role.ADMIN])


# ----- Factories DB -----


# Méthodes HTTP sans effet de bord. Starlette sert `HEAD` par la route `GET` correspondante, qui traverse donc les mêmes dépendances. `OPTIONS` n'atteint aucune route — le contrôle préalable reçoit sa réponse du middleware CORS, et une requête nue tombe en 405 — et figure ici pour la route qui viendrait à le déclarer.
READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _open_connection(request: Request) -> Connection:
    """Connexion tirée de l'engine, avec les caractéristiques de la requête en cours.

    Sur une méthode de lecture, la transaction s'ouvre **en lecture seule** : PostgreSQL refuse alors tout INSERT, UPDATE, DELETE ou DDL par une erreur `25006`, y compris celui qu'un service émettrait. La caractéristique se pose avant tout statement, sur une connexion dont la transaction n'est pas encore ouverte, et SQLAlchemy la remet à zéro au retour de la connexion dans le pool. La transaction a aussi un plafond de durée par requête SQL (`api_read_statement_timeout_s`).

    Point de passage unique des connexions ouvertes pendant une requête : celle que `db_conn` sert aux dépendances, et celles que `connection_factory` remet à une lecture parallélisée. La règle vaut donc pour toutes, quel que soit le code qui les consomme.
    """
    conn = get_sync_engine().connect()
    if request.method in READ_ONLY_METHODS:
        conn.execution_options(postgresql_readonly=True)
        conn.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{settings.api_read_statement_timeout_s}s'"
        )
    return conn


def connection_factory(request: Request) -> Callable[[], Connection]:
    """Fabrique de connexions supplémentaires, sous les mêmes caractéristiques que celle de la requête.

    Sert la lecture qui répartit son travail sur plusieurs connexions — les facettes de publications, calculées en parallèle. L'adapter la reçoit par sa construction au lieu d'atteindre l'engine : la lecture seule vaut alors pour toute connexion née pendant la requête, et un contrat d'import tient les adapters à l'écart de l'engine.

    L'appelant referme chaque connexion qu'il ouvre, `Connection` étant son propre gestionnaire de contexte.
    """
    return lambda: _open_connection(request)


def db_conn(request: Request) -> Iterator[Connection]:
    """Connexion de la requête, servie aux routes par `DbConn`. Sa transaction est celle de la requête.

    Une requête d'écriture qui aboutit est committée en sortie, avec les événements d'audit qu'elle a émis (`record_pending_events`) ; une exception l'annule. Cette sortie précède l'envoi de la réponse (`scope="function"`) : un GET ou une tâche de fond déclenchés ensuite lisent l'état committé. Les services ne committent pas ; le pipeline et les scripts committent eux-mêmes.

    Toute dépendance qui en dérive (repositories et query adapters) partage la même connexion. Sur une méthode de lecture, la connexion s'ouvre en lecture seule (cf. `_open_connection`).
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


# Seule déclaration de la connexion de la requête. Une déclaration d'un autre scope ouvrirait une
# seconde connexion, avec sa propre transaction.
DbConn = Annotated[Connection, Depends(db_conn, scope="function")]


# ----- Session, sur la connexion de la requête -----


def session_user(request: Request, conn: DbConn) -> SessionUser | None:
    """Utilisateur de la session en cours, ou `None`, sans jamais refuser l'appel.

    Sert les lectures dont le contenu dépend de l'appelant : la configuration, dont une part est réservée à l'administration, et l'état de la session.
    """
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
# Un service par agrégat, construit sur la connexion reçue : celle de la requête pour une route,
# celle de la tâche de fond pour une tâche de fond, celle du script pour un script.


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
    """Exécute `work` sur une connexion à elle, hors du cycle de requête.

    Une tâche de fond s'exécute pendant l'envoi de la réponse, en parallèle de la requête qui l'a enregistrée : la connexion de celle-ci appartient à un autre contexte, et la partager laisserait une transaction ouverte (idle in transaction). `engine.begin()` commite en sortie, annule sur exception, et ferme dans les deux cas.

    L'exception est piégée et loguée : une tâche de fond n'a personne à qui la remonter, la réponse étant partie. `work` voit les écritures de la requête, committées avant l'envoi de sa réponse.
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
    """Tâche de fond : propage `in_perimeter` après une review d'affiliation.

    Le recalcul peut toucher des dizaines de milliers de `source_contributions`, d'où son décorrélage de la réponse admin.
    """
    _run_detached(
        "propagation d'in_perimeter",
        lambda conn: address_service(conn).propagate_in_perimeter_for_addresses(address_ids),
    )
