"""Dépendances partagées des routers : factories DB, tâches de fond, réglages du serveur.

`db_conn` fournit aux routes, par `Depends(...)`, la connexion sur laquelle les factories câblent les query services et les repositories.

La session admin vit dans `session.py` ; ce module n'en expose que le nom d'utilisateur attendu, par `Depends(...)`.
"""

import logging
from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Connection

from application.ports.api.addresses_queries import AddressesQueries
from application.ports.api.authorships_queries import AuthorshipsQueries
from application.ports.api.config_queries import ConfigQueries
from application.ports.api.countries_queries import CountriesQueries
from application.ports.api.entity_facet import EntityLabelQueries
from application.ports.api.feedback_queries import FeedbackQueries
from application.ports.api.hal_problems_queries import HalProblemsQueries
from application.ports.api.journals_queries import JournalQueries
from application.ports.api.perimeters_queries import PerimetersQueries
from application.ports.api.persons_queries import PersonsQueries
from application.ports.api.pipeline_phase_executions_queries import PhaseExecutionsQueries
from application.ports.api.publication_duplicates_queries import PublicationDuplicatesQueries
from application.ports.api.publications_queries import PublicationsQueries
from application.ports.api.publishers_queries import PublisherQueries
from application.ports.api.stats_queries import StatsQueries
from application.ports.api.structures_queries import StructuresQueries
from application.ports.api.subjects_queries import SubjectsQueries
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.pipeline.perimeter_structures import PerimeterStructuresQueries
from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.config_repository import ConfigRepository
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
from infrastructure.queries.api.authorships import PgAuthorshipsQueries
from infrastructure.queries.api.config import PgConfigQueries
from infrastructure.queries.api.countries import PgCountriesQueries
from infrastructure.queries.api.entity_labels import PgEntityLabelQueries
from infrastructure.queries.api.feedback import PgFeedbackQueries
from infrastructure.queries.api.hal_problems import PgHalProblemsQueries
from infrastructure.queries.api.journals import PgJournalQueries
from infrastructure.queries.api.persons import PgPersonsQueries
from infrastructure.queries.api.pipeline_phase_executions import PgPhaseExecutionsQueries
from infrastructure.queries.api.publication_duplicates import PgPublicationDuplicatesQueries
from infrastructure.queries.api.publications import PgPublicationsQueries
from infrastructure.queries.api.publishers import PgPublisherQueries
from infrastructure.queries.api.stats import PgStatsQueries
from infrastructure.queries.api.structures import PgStructuresQueries
from infrastructure.queries.api.subjects import PgSubjectsQueries
from infrastructure.queries.perimeter import PgPerimetersQueries, PgPerimeterStructuresQueries
from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries
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
from infrastructure.repositories.config_repository import PgConfigRepository
from infrastructure.settings import settings
from interfaces.api.session import read_session

logger = logging.getLogger(__name__)


# ----- Session admin -----


def get_admin_user() -> str:
    """Username admin attendu (depuis `infrastructure.settings`).

    Exposé en `Depends(...)` pour que les routers n'importent pas `infrastructure.settings` directement (règle 4 de `docs/architecture/01-vue-d-ensemble.md`, tenue par un contrat import-linter).
    """
    return settings.admin_user


def current_admin_user(request: Request) -> str | None:
    """Utilisateur porté par la session en cours, ou `None` sans session valide.

    Sert les lectures dont le contenu dépend de l'appelant sans lui être interdit — la configuration, dont une part est publique et le reste réservé.
    """
    token = request.cookies.get("session")
    return read_session(token) if token else None


def require_admin(request: Request) -> str:
    """Exige une session valide et rend l'utilisateur qu'elle porte, ou lève un 401.

    Le middleware d'`app.py` garde les écritures en filtrant sur la méthode HTTP ; toute lecture est donc ouverte. Cette dépendance couvre les rares lectures qui ne peuvent pas l'être, et se pose sur la route qu'elle protège plutôt que sur un préfixe d'URL.
    """
    token = request.cookies.get("session")
    admin_user = read_session(token) if token else None
    if not admin_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return admin_user


# ----- Factories DB -----


def db_conn(request: Request) -> Iterator[Connection]:
    """Connection SQLAlchemy ouverte pour la durée de la requête, via `Depends(db_conn)`.

    La persistance est la prérogative du use case : un command handler de la couche application appelle `conn.commit()` lui-même avant de retourner, ce qui persiste la donnée *avant* l'envoi de la réponse. FastAPI exécute le teardown des dépendances `yield` après cet envoi : un commit placé ici arriverait trop tard, et un GET ou une tâche de fond déclenchés dans l'intervalle liraient l'état antérieur.

    En sortie, la transaction est **annulée** (`rollback`) : une session de lecture, ou une session dont le command handler a committé, n'a rien à persister. Du DML qui atteint cette sortie sans commit signale une écriture qui contourne les command handlers : le rollback la perd, et un warning la signale. Toute dépendance qui en dérive (repositories et query adapters) partage la même connexion.
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
                    "command handler committant ; le rollback de fin de db_conn l'a perdue.",
                    request.method,
                    request.url.path,
                )


def subjects_queries(
    conn: Connection = Depends(db_conn),
) -> SubjectsQueries:
    return PgSubjectsQueries(conn)


def authorships_queries(conn: Connection = Depends(db_conn)) -> AuthorshipsQueries:
    return PgAuthorshipsQueries(conn)


def countries_queries(conn: Connection = Depends(db_conn)) -> CountriesQueries:
    return PgCountriesQueries(conn)


def config_queries(conn: Connection = Depends(db_conn)) -> ConfigQueries:
    return PgConfigQueries(conn)


def config_repository(conn: Connection = Depends(db_conn)) -> ConfigRepository:
    return PgConfigRepository(conn)


def hal_problems_queries(
    conn: Connection = Depends(db_conn),
) -> HalProblemsQueries:
    return PgHalProblemsQueries(conn)


def audit_repo(conn: Connection = Depends(db_conn)) -> AuditRepository:
    return audit_repository(conn)


def publication_repo(conn: Connection = Depends(db_conn)) -> PublicationRepository:
    return publication_repository(conn)


def publication_duplicates_queries(
    conn: Connection = Depends(db_conn),
) -> PublicationDuplicatesQueries:
    return PgPublicationDuplicatesQueries(conn)


def person_repo(conn: Connection = Depends(db_conn)) -> PersonRepository:
    return person_repository(conn)


def journal_queries(conn: Connection = Depends(db_conn)) -> JournalQueries:
    return PgJournalQueries(conn)


def journal_repo(conn: Connection = Depends(db_conn)) -> JournalRepository:
    return journal_repository(conn)


def publisher_queries(conn: Connection = Depends(db_conn)) -> PublisherQueries:
    return PgPublisherQueries(conn)


def publisher_repo(conn: Connection = Depends(db_conn)) -> PublisherRepository:
    return publisher_repository(conn)


def perimeter_repo(conn: Connection = Depends(db_conn)) -> PerimeterRepository:
    return perimeter_repository(conn)


def perimeters_queries(
    conn: Connection = Depends(db_conn),
) -> PerimetersQueries:
    return PgPerimetersQueries(conn)


def feedback_queries(conn: Connection = Depends(db_conn)) -> FeedbackQueries:
    return PgFeedbackQueries(conn)


def stats_queries(conn: Connection = Depends(db_conn)) -> StatsQueries:
    return PgStatsQueries(conn)


def entity_label_queries(conn: Connection = Depends(db_conn)) -> EntityLabelQueries:
    return PgEntityLabelQueries(conn)


def structure_repo(conn: Connection = Depends(db_conn)) -> StructureRepository:
    return structure_repository(conn)


def structures_queries(conn: Connection = Depends(db_conn)) -> StructuresQueries:
    return PgStructuresQueries(conn)


def publications_queries(
    conn: Connection = Depends(db_conn),
) -> PublicationsQueries:
    return PgPublicationsQueries(conn)


def authorship_repo(conn: Connection = Depends(db_conn)) -> AuthorshipRepository:
    return authorship_repository(conn)


def address_repo(conn: Connection = Depends(db_conn)) -> AddressRepository:
    return address_repository(conn)


def persons_queries(conn: Connection = Depends(db_conn)) -> PersonsQueries:
    return PgPersonsQueries(conn)


def pipeline_phase_executions_queries(
    conn: Connection = Depends(db_conn),
) -> PhaseExecutionsQueries:
    return PgPhaseExecutionsQueries(conn)


def addresses_queries(conn: Connection = Depends(db_conn)) -> AddressesQueries:
    return PgAddressesQueries(conn)


# `PgPerimeterStructuresQueries` est sans état (la connexion est passée aux méthodes) : un singleton par processus suffit.
_perimeter_queries_singleton: PerimeterStructuresQueries = PgPerimeterStructuresQueries()


def get_perimeter_queries() -> PerimeterStructuresQueries:
    return _perimeter_queries_singleton


# `PgMetadataCorrectionQueries` est sans état (la connexion est passée aux méthodes) : un singleton par processus suffit.
_metadata_correction_queries_singleton: MetadataCorrectionQueries = PgMetadataCorrectionQueries()


def metadata_correction_queries() -> MetadataCorrectionQueries:
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


def bg_propagate_countries(address_ids: list[int]) -> None:
    """Tâche de fond : propage les pays des adresses vers les publications."""
    _run_detached(
        "propagation des pays",
        lambda conn: countries_service.propagate_countries_to_publications(
            address_ids, repo=address_repository(conn)
        ),
    )


def bg_propagate_in_perimeter(address_ids: list[int]) -> None:
    """Tâche de fond : propage `in_perimeter` après une review d'affiliation.

    Le recalcul peut toucher des dizaines de milliers de `source_authorships`, d'où son décorrélage de la réponse admin.
    """
    _run_detached(
        "propagation d'in_perimeter",
        lambda conn: propagate_in_perimeter_for_addresses(
            conn,
            address_ids,
            repo=authorship_repository(conn),
            perimeter_queries=get_perimeter_queries(),
        ),
    )
