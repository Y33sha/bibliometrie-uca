"""Factories pour accéder aux implémentations concrètes des repositories.

La couche application importe ces fonctions plutôt que les classes
concrètes Pg* : elle ne dépend que de ce module (point de câblage
d'infrastructure) et des Protocols dans application/ports/repositories/,
jamais des classes d'implémentation.

Pour changer d'implémentation (tests avec fake, futur changement de
SGBD…) : remplacer le corps d'une factory par la nouvelle impl, sans
toucher au code de l'application.

Usage :
    from infrastructure.repositories import person_repository

    def set_rejected(cur, person_id, rejected):
        person_repository(cur).set_rejected(person_id, rejected)
"""

from sqlalchemy import Connection

from application.ports.repositories.address_repository import AddressRepository
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.person_repository import PersonRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.ports.repositories.structure_repository import StructureRepository
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


def address_repository(conn: Connection) -> AddressRepository:
    """Retourne un AddressRepository lié à la Connection SA donnée."""
    return PgAddressRepository(conn)


def audit_repository(conn: Connection) -> AuditRepository:
    """Retourne un AuditRepository lié à la Connection SA donnée."""
    return PgAuditRepository(conn)


def authorship_repository(conn: Connection) -> AuthorshipRepository:
    """Retourne un AuthorshipRepository lié à la Connection SA donnée."""
    return PgAuthorshipRepository(conn)


def config_store(conn: Connection) -> PgConfig:
    """Retourne un ConfigStore (port défini dans application/ports/config.py)."""
    return PgConfig(conn)


def journal_repository(conn: Connection) -> JournalRepository:
    """Retourne un JournalRepository lié à la Connection SA donnée."""
    return PgJournalRepository(conn)


def perimeter_repository(conn: Connection) -> PerimeterRepository:
    """Retourne un PerimeterRepository lié à la Connection SA donnée."""
    return PgPerimeterRepository(conn)


def person_repository(conn: Connection) -> PersonRepository:
    """Retourne un PersonRepository lié à la Connection SA donnée."""
    return PgPersonRepository(conn)


def publication_repository(conn: Connection) -> PublicationRepository:
    """Retourne un PublicationRepository lié à la Connection SA donnée."""
    return PgPublicationRepository(conn)


def publisher_repository(conn: Connection) -> PublisherRepository:
    """Retourne un PublisherRepository lié à la Connection SA donnée."""
    return PgPublisherRepository(conn)


def structure_repository(conn: Connection) -> StructureRepository:
    """Retourne un StructureRepository lié à la Connection SA donnée."""
    return PgStructureRepository(conn)
