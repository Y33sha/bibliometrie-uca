"""Dépendances partagées des routers : factories DB, tâches de fond, réglages du serveur.

`DbConn` fournit aux routes la connexion de la requête, sur laquelle les factories câblent les query services et les repositories.

La session admin vit dans `session.py` ; ce module n'en expose que le nom d'utilisateur attendu, par `Depends(...)`.
"""

import logging
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Connection

from application.audit_log import record_pending_events
from application.ports.pipeline.countries import CountryRecompute as CountryRecomputePort
from application.ports.pipeline.perimeter_structures import (
    PerimeterStructures as PerimeterStructuresPort,
)
from application.ports.read_models.addresses_queries import AddressesQueries
from application.ports.read_models.config_queries import ConfigQueries
from application.ports.read_models.contributions_queries import ContributionsQueries
from application.ports.read_models.countries_queries import CountriesQueries
from application.ports.read_models.entity_labels_queries import EntityLabelQueries
from application.ports.read_models.feedback_queries import FeedbackQueries
from application.ports.read_models.hal_problems_queries import HalProblemsQueries
from application.ports.read_models.monographs_queries import MonographQueries
from application.ports.read_models.perimeters_queries import PerimetersQueries
from application.ports.read_models.persons_queries import PersonsQueries
from application.ports.read_models.pipeline_runs_queries import PipelineRunsQueries
from application.ports.read_models.publications_queries import PublicationsQueries
from application.ports.read_models.publishers_queries import PublisherQueries
from application.ports.read_models.serials_queries import SerialQueries
from application.ports.read_models.stats_queries import StatsQueries
from application.ports.read_models.structures_queries import StructuresQueries
from application.ports.read_models.subjects_queries import SubjectsQueries
from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.config_repository import ConfigRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.structure_repository import StructureRepository
from application.services.addresses import (
    countries as countries_service,
    structure_links as structure_links_service,
)
from application.services.contributions import ContributionService
from application.services.persons import PersonService
from application.services.publishers import PublisherService
from application.services.serials import SerialService
from domain.merge import MergedEntity
from infrastructure.db.engine import get_sync_engine
from infrastructure.read_models.addresses import PgAddressesQueries
from infrastructure.read_models.config import PgConfigQueries
from infrastructure.read_models.contributions import PgContributionsQueries
from infrastructure.read_models.countries import PgCountriesQueries
from infrastructure.read_models.entity_labels import PgEntityLabelQueries
from infrastructure.read_models.feedback import PgFeedbackQueries
from infrastructure.read_models.hal_problems import PgHalProblemsQueries
from infrastructure.read_models.merge_redirects import PgMergeRedirectQueries
from infrastructure.read_models.monographs import PgMonographQueries
from infrastructure.read_models.perimeters import PgPerimetersQueries
from infrastructure.read_models.persons import PgPersonsQueries
from infrastructure.read_models.pipeline_runs import PgPipelineRunsQueries
from infrastructure.read_models.publications import PgPublicationsQueries
from infrastructure.read_models.publishers import PgPublisherQueries
from infrastructure.read_models.serials import PgSerialQueries
from infrastructure.read_models.stats import PgStatsQueries
from infrastructure.read_models.structures import PgStructuresQueries
from infrastructure.read_models.subjects import PgSubjectsQueries
from infrastructure.repositories import (
    address_repository,
    audit_repository,
    contribution_repository,
    perimeter_repository,
    person_repository,
    publisher_repository,
    serial_repository,
    structure_repository,
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


# ----- Session admin -----


def get_admin_user() -> str:
    """Username admin attendu (depuis `infrastructure.settings`).

    Exposé en `Depends(...)` pour que les routers n'importent pas `infrastructure.settings` directement (tenu par un contrat import-linter).
    """
    return settings.admin_user


def admin_user_or_none(request: Request) -> str | None:
    """Utilisateur de la session en cours, ou `None` faute de session valide — sans jamais refuser l'appel.

    Sert les lectures dont le contenu dépend de l'appelant sans lui être interdit : la configuration, dont une part est publique et le reste réservé à une session.
    """
    token = request.cookies.get("session")
    return read_session(token) if token else None


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


def subjects_queries(
    conn: DbConn,
) -> SubjectsQueries:
    return PgSubjectsQueries(conn)


def contributions_queries(conn: DbConn) -> ContributionsQueries:
    return PgContributionsQueries(conn)


def countries_queries(conn: DbConn) -> CountriesQueries:
    return PgCountriesQueries(conn)


def config_queries(conn: DbConn) -> ConfigQueries:
    return PgConfigQueries(conn)


def config_repository(conn: DbConn) -> ConfigRepository:
    return PgConfigRepository(conn)


def hal_problems_queries(
    conn: DbConn,
) -> HalProblemsQueries:
    return PgHalProblemsQueries(conn)


def person_service(conn: DbConn) -> PersonService:
    return PersonService(
        persons=person_repository(conn),
        contributions=contribution_repository(conn),
        perimeter_recompute=PublicationPerimeterRecompute(conn),
    )


def serial_queries(conn: DbConn) -> SerialQueries:
    return PgSerialQueries(conn)


def serial_service(conn: DbConn) -> SerialService:
    return SerialService(
        serials=serial_repository(conn), recompute=SerialRecompute(conn), conn=conn
    )


def monograph_queries(conn: DbConn) -> MonographQueries:
    return PgMonographQueries(conn)


def publisher_queries(conn: DbConn) -> PublisherQueries:
    return PgPublisherQueries(conn)


def publisher_service(conn: DbConn) -> PublisherService:
    return PublisherService(
        publishers=publisher_repository(conn),
        serials=serial_repository(conn),
        serial_service=serial_service(conn),
        publication_count_recompute=PublicationCountRecompute(conn),
    )


def perimeter_repo(conn: DbConn) -> PerimeterRepository:
    return perimeter_repository(conn)


def perimeters_queries(
    conn: DbConn,
) -> PerimetersQueries:
    return PgPerimetersQueries(conn)


def feedback_queries(conn: DbConn) -> FeedbackQueries:
    return PgFeedbackQueries(conn)


def stats_queries(conn: DbConn) -> StatsQueries:
    return PgStatsQueries(conn)


def entity_label_queries(conn: DbConn) -> EntityLabelQueries:
    return PgEntityLabelQueries(conn)


def entity_detail(entity: MergedEntity) -> Callable[[Request, Connection], EntityDetail]:
    """Dépendance d'une route de détail de `entity` (`interfaces.api.entity_detail`)."""

    def dependency(request: Request, conn: DbConn) -> EntityDetail:
        return EntityDetail(entity, request, PgMergeRedirectQueries(conn))

    return dependency


def structure_repo(conn: DbConn) -> StructureRepository:
    return structure_repository(conn)


def structures_queries(conn: DbConn) -> StructuresQueries:
    return PgStructuresQueries(conn)


def publications_queries(
    conn: DbConn,
    open_connection: Callable[[], Connection] = Depends(connection_factory),
) -> PublicationsQueries:
    return PgPublicationsQueries(conn, open_connection=open_connection)


def contribution_service(conn: DbConn) -> ContributionService:
    return ContributionService(
        persons=person_repository(conn),
        contributions=contribution_repository(conn),
        perimeter_recompute=PublicationPerimeterRecompute(conn),
    )


def address_repo(conn: DbConn) -> AddressRepository:
    return address_repository(conn)


def persons_queries(conn: DbConn) -> PersonsQueries:
    return PgPersonsQueries(conn)


def pipeline_runs_queries(
    conn: DbConn,
) -> PipelineRunsQueries:
    return PgPipelineRunsQueries(conn)


def addresses_queries(conn: DbConn) -> AddressesQueries:
    return PgAddressesQueries(conn)


# Recalculs du pipeline, construits comme les repositories sur la connexion de la requête.


def get_perimeter_structures(conn: DbConn) -> PerimeterStructuresPort:
    """Clôture des tutelles des périmètres."""
    return PerimeterStructures(conn)


def country_recompute(conn: DbConn) -> CountryRecomputePort:
    """Résolution des pays d'adresses et recalcul ciblé des pays des publications, exposés par le pipeline."""
    return CountryRecompute(conn)


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
        lambda conn: countries_service.propagate_countries_to_publications(
            address_ids, country_recompute=CountryRecompute(conn)
        ),
    )


def bg_propagate_in_perimeter(address_ids: list[int]) -> None:
    """Tâche de fond : propage `in_perimeter` après une review d'affiliation.

    Le recalcul peut toucher des dizaines de milliers de `source_contributions`, d'où son décorrélage de la réponse admin.
    """
    _run_detached(
        "propagation d'in_perimeter",
        lambda conn: structure_links_service.propagate_in_perimeter_for_addresses(
            address_ids,
            repo=contribution_repository(conn),
            perimeter_structures=PerimeterStructures(conn),
            perimeter_recompute=SourceContributionPerimeterRecompute(conn),
        ),
    )
