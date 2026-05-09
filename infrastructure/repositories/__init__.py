"""Factories pour accéder aux implémentations concrètes des repositories.

La couche application importe ces fonctions plutôt que les classes
concrètes Pg* : elle ne dépend que de ce module (point de câblage
d'infrastructure) et des Protocols dans domain/ports/, jamais des
classes d'implémentation.

Pour changer d'implémentation (tests avec fake, futur changement de
SGBD…) : remplacer le corps d'une factory par la nouvelle impl, sans
toucher au code de l'application.

Usage :
    from infrastructure.repositories import person_repository

    def set_rejected(cur, person_id, rejected):
        person_repository(cur).set_rejected(person_id, rejected)

Les agrégats Address, Authorship, Perimeter et Structure ne sont
exposés qu'en async (seuls consommateurs = routers API), de même que
la table clé/valeur Config (port `application.ports.config.AsyncConfigStore`).
Journal, Person et Publication existent dans les deux variantes
(sync pour pipeline/CLI, async pour API).
"""

from typing import Any

from domain.ports.address_repository import AddressRepository, AsyncAddressRepository
from domain.ports.audit_repository import AsyncAuditRepository, AuditRepository
from domain.ports.authorship_repository import AsyncAuthorshipRepository, AuthorshipRepository
from domain.ports.journal_repository import AsyncJournalRepository, JournalRepository
from domain.ports.perimeter_repository import AsyncPerimeterRepository, PerimeterRepository
from domain.ports.person_repository import AsyncPersonRepository, PersonRepository
from domain.ports.publication_repository import AsyncPublicationRepository, PublicationRepository
from domain.ports.publisher_repository import AsyncPublisherRepository, PublisherRepository
from domain.ports.structure_repository import AsyncStructureRepository, StructureRepository
from infrastructure.db.queries.config import PgAsyncConfig, PgConfig

from .address_repository import PgAddressRepository
from .async_address_repository import PgAsyncAddressRepository
from .async_audit_repository import PgAsyncAuditRepository
from .async_authorship_repository import PgAsyncAuthorshipRepository
from .async_journal_repository import PgAsyncJournalRepository
from .async_perimeter_repository import PgAsyncPerimeterRepository
from .async_person_repository import PgAsyncPersonRepository
from .async_publication_repository import PgAsyncPublicationRepository
from .async_publisher_repository import PgAsyncPublisherRepository
from .async_structure_repository import PgAsyncStructureRepository
from .audit_repository import PgAuditRepository
from .authorship_repository import PgAuthorshipRepository
from .journal_repository import PgJournalRepository
from .perimeter_repository import PgPerimeterRepository
from .person_repository import PgPersonRepository
from .publication_repository import PgPublicationRepository
from .publisher_repository import PgPublisherRepository
from .structure_repository import PgStructureRepository


def address_repository(conn: Any) -> AddressRepository:
    """Retourne un AddressRepository lié à la Connection SA donnée."""
    return PgAddressRepository(conn)


def audit_repository(conn_or_cur: Any) -> AuditRepository:
    """Retourne un AuditRepository lié au cur psycopg ou Connection SA donné."""
    return PgAuditRepository(conn_or_cur)


def authorship_repository(conn: Any) -> AuthorshipRepository:
    """Retourne un AuthorshipRepository lié à la Connection SA donnée."""
    return PgAuthorshipRepository(conn)


def config_store(conn: Any) -> PgConfig:
    """Retourne un ConfigStore (port défini dans application/ports/config.py).

    Variante sync de `async_config_store`. Cohabite jusqu'à la
    suppression de la moitié async (Phase 3 sync-async-deduplication).
    """
    return PgConfig(conn)


def journal_repository(conn_or_cur: Any) -> JournalRepository:
    """Retourne un JournalRepository lié au cur psycopg ou Connection SA donné."""
    return PgJournalRepository(conn_or_cur)


def perimeter_repository(conn: Any) -> PerimeterRepository:
    """Retourne un PerimeterRepository lié à la Connection SA donnée."""
    return PgPerimeterRepository(conn)


def person_repository(conn_or_cur: Any) -> PersonRepository:
    """Retourne un PersonRepository lié au cur psycopg ou Connection SA donné."""
    return PgPersonRepository(conn_or_cur)


def publication_repository(conn_or_cur: Any) -> PublicationRepository:
    """Retourne un PublicationRepository lié au cur psycopg ou Connection SA donné."""
    return PgPublicationRepository(conn_or_cur)


def publisher_repository(conn_or_cur: Any) -> PublisherRepository:
    """Retourne un PublisherRepository lié au cur psycopg ou Connection SA donné."""
    return PgPublisherRepository(conn_or_cur)


def structure_repository(conn: Any) -> StructureRepository:
    """Retourne un StructureRepository lié à la Connection SA donnée."""
    return PgStructureRepository(conn)


# ── Factories async ────────────────────────────────────────────────


def async_address_repository(cur: Any) -> AsyncAddressRepository:
    return PgAsyncAddressRepository(cur)


def async_audit_repository(cur: Any) -> AsyncAuditRepository:
    return PgAsyncAuditRepository(cur)


def async_authorship_repository(cur: Any) -> AsyncAuthorshipRepository:
    return PgAsyncAuthorshipRepository(cur)


def async_config_store(cur: Any) -> PgAsyncConfig:
    """Retourne un AsyncConfigStore (port défini dans application/ports/config.py).

    Le type de retour est annoté avec la classe concrète pour respecter
    la règle DDD `infrastructure ⊥ application` ; les call sites côté
    application/ typent leur paramètre via le Protocol AsyncConfigStore
    (duck typing structurel).
    """
    return PgAsyncConfig(cur)


def async_journal_repository(cur: Any) -> AsyncJournalRepository:
    return PgAsyncJournalRepository(cur)


def async_perimeter_repository(cur: Any) -> AsyncPerimeterRepository:
    return PgAsyncPerimeterRepository(cur)


def async_person_repository(cur: Any) -> AsyncPersonRepository:
    return PgAsyncPersonRepository(cur)


def async_publication_repository(cur: Any) -> AsyncPublicationRepository:
    return PgAsyncPublicationRepository(cur)


def async_publisher_repository(cur: Any) -> AsyncPublisherRepository:
    return PgAsyncPublisherRepository(cur)


def async_structure_repository(cur: Any) -> AsyncStructureRepository:
    return PgAsyncStructureRepository(cur)
