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
"""

from typing import Any

from domain.ports.address_repository import AddressRepository
from domain.ports.audit_repository import AuditRepository
from domain.ports.authorship_repository import AuthorshipRepository
from domain.ports.journal_repository import JournalRepository
from domain.ports.perimeter_repository import PerimeterRepository
from domain.ports.person_repository import PersonRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.ports.structure_repository import StructureRepository
from infrastructure.db.queries.config import PgConfig

from .address_repository import PgAddressRepository
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
    """Retourne un ConfigStore (port défini dans application/ports/config.py)."""
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
