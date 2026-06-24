"""Shared dependencies : SPA static files, auth helpers, DB factories.

`db_conn_sync` ouvre une `Connection` SQLAlchemy via `engine.connect()`
(commit-as-you-go : le handler d'écriture commit lui-même) et la fournit aux
routes via `Depends(...)`. Les factories câblent les query services et
repositories sur cette Connection.
"""

import hashlib
import hmac
import logging
import os
import time
from collections.abc import Iterator

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection
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
from application.ports.api.pipeline_runs_queries import PipelineRunsQueries
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
from infrastructure.db.dml_guard import has_uncommitted_dml, reset_dml_flag
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.api.addresses import PgAddressesQueries
from infrastructure.queries.api.admin_feedback import PgAdminFeedbackQueries
from infrastructure.queries.api.hal_problems import PgHalProblemsQueries
from infrastructure.queries.api.journals import PgJournalQueries
from infrastructure.queries.api.laboratories import PgLaboratoriesQueries
from infrastructure.queries.api.person_duplicates import PgPersonDuplicatesQueries
from infrastructure.queries.api.persons import PgPersonsQueries
from infrastructure.queries.api.pipeline_runs import PgPipelineRunsQueries
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

# ----- SPA Static Files -----

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = os.path.join(PROJECT_ROOT, "interfaces", "frontend", "build")


class SPAStaticFiles(StaticFiles):
    """Sert le build SvelteKit (adapter-static).

    Deux particularités du format prérendu :
    - les pages prérendues sont écrites en `<route>.html` (ex.
      `docs/glossaire.html`) : on retente avec l'extension `.html` quand le
      chemin nu est introuvable ;
    - les routes purement client-side (ssr=false, non prérendues) retombent
      sur `index.html` (routage SPA côté client).
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except Exception:
            if not path.endswith(".html"):
                try:
                    return await super().get_response(f"{path}.html", scope)
                except Exception:
                    pass
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


def db_conn_sync(request: Request) -> Iterator[Connection]:
    """Connection SA sync ouverte pour les routers `def`, via `Depends(db_conn_sync)`.

    Style « commit as you go » : un handler d'écriture (command handler de la
    couche application) appelle `conn.commit()` lui-même, avant de retourner.
    C'est nécessaire pour que la donnée soit persistée *avant* l'envoi de la
    réponse — FastAPI exécute le teardown des dépendances `yield` après l'envoi,
    donc un commit fait ici en sortie arriverait trop tard (un GET ou une tâche
    de fond déclenchés juste après liraient l'état pré-commit).

    En sortie, un commit de fin persiste ce qu'un handler n'aurait pas commité
    (garde-fou pendant la migration des handlers d'écriture). Quand ce commit de
    fin rattrape du DML non committé (endpoint non migré, ou écriture parasite
    dans un routeur), il émet un warning : la bascule finale (commit de fin →
    rollback, qui retire le filet) est pilotée par l'extinction de ce warning sur
    tout le trafic, pas par la croyance que tout est migré. Sur exception, la
    transaction est annulée. Toute dépendance qui en dérive (`*_repo` sync, query
    adapters sync) partage la même connexion.
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
            # Lu avant le commit garde-fou : ce commit réarmerait le flag.
            escaped_dml = has_uncommitted_dml(conn)
            conn.commit()
            if escaped_dml:
                logger.warning(
                    "Écriture non committée rattrapée par le commit de fin de db_conn_sync : "
                    "%s %s a émis du DML hors command handler (endpoint non migré ou écriture "
                    "parasite ; cf. docs/chantiers/CODE_commit-avant-reponse.md).",
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


def pipeline_runs_queries_sync(
    conn: Connection = Depends(db_conn_sync),
) -> PipelineRunsQueries:
    return PgPipelineRunsQueries(conn)


def addresses_queries_sync(conn: Connection = Depends(db_conn_sync)) -> AddressesQueries:
    return PgAddressesQueries(conn)


# PgPerimeterQueries est sans état (la connexion est passée aux méthodes),
# donc un singleton par processus suffit.
_perimeter_queries_sync_singleton: PerimeterQueries = PgPerimeterQueries()


def get_perimeter_queries_sync() -> PerimeterQueries:
    """Retourne le singleton sync de `PerimeterQueries`."""
    return _perimeter_queries_sync_singleton


# `PgMetadataCorrectionQueries` est sans état (connexion passée aux méthodes) → singleton.
_metadata_correction_queries_singleton: MetadataCorrectionQueries = PgMetadataCorrectionQueries()


def metadata_correction_queries_sync() -> MetadataCorrectionQueries:
    """Retourne le singleton sync de `MetadataCorrectionQueries` (hooks admin journaux)."""
    return _metadata_correction_queries_singleton


# ----- Tâches de fond (BackgroundTasks) -----
#
# Contrat (cf. chantier CODE_background-jobs, phase hygiène) : une BG task ouvre
# TOUJOURS sa propre connexion via `with engine.begin()` (commit/rollback + close
# en sortie, même sur exception) et enveloppe son corps dans un `try/except` qui
# logue — jamais réutiliser la connexion de la requête (elle appartient à un autre
# contexte et tourne en parallèle) et jamais laisser une transaction ouverte (idle
# in transaction). Note : une BG task s'exécute pendant l'envoi de la réponse, donc
# AVANT le commit de fin de la requête (cf. chantier CODE_commit-avant-reponse) ;
# elle ne voit les écritures de la requête que si le handler les a commitées avant
# de retourner.


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


def bg_propagate_in_perimeter_sync(address_ids: list[int]) -> None:
    """Tâche de fond sync : propager `in_perimeter` après une review d'affiliation.

    Lancée hors cycle de requête (`BackgroundTasks`) : composition manuelle,
    connexion DB propre (jamais celle de la requête). Le recompute peut toucher
    des dizaines de milliers de source_authorships — on le décorrèle de la réponse
    admin (cf. `docs/chantiers/CODE_background-jobs.md`).
    """
    import logging

    from application.authorships.core import propagate_in_perimeter_for_addresses

    logger = logging.getLogger(__name__)
    try:
        engine = get_sync_engine()
        with engine.begin() as conn:
            propagate_in_perimeter_for_addresses(
                conn,
                address_ids,
                repo=authorship_repository(conn),
                perimeter_queries=get_perimeter_queries_sync(),
            )
    except Exception:
        logger.exception("Erreur propagation in_perimeter en background")


# ----- Périmètre APC : structures considérées comme "internes" -----


def get_apc_structure_ids_sync() -> list[int]:
    """Structures considérées comme "internes" pour la catégorisation APC.

    Réutilise le périmètre `perimeter_persons` (avec expansion
    `est_tutelle_de`) : UCA + tous ses labos UCA. Une publication APC
    est classée "uca" si au moins un de ses `apc_payments.budget_structure_id`
    est dans cet ensemble.

    Pas de cache : un lookup PK par requête API (~µs), invalidation
    transparente si le périmètre change via `/admin/config` ou si les
    structures du périmètre évoluent.
    """
    from infrastructure.queries.perimeter import get_persons_structure_ids_list

    engine = get_sync_engine()
    with engine.connect() as conn:
        return get_persons_structure_ids_list(conn)
